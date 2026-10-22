#!/usr/bin/env python3
"""hydracode: router de modelos con fallback · by carlosplata.dev
Uso: hydracode <rol> "tarea" [--private] [< archivo]"""
import json, os, sys, time, subprocess, urllib.request, urllib.error, pathlib, datetime

CFG = pathlib.Path(os.environ.get("HYDRACODE_HOME", pathlib.Path.home() / ".config/hydracode"))
SKILL = pathlib.Path(__file__).resolve().parent
F = {k: CFG / v for k, v in dict(prov="providers.json", sec="secrets.json",
                                 health="health.json", usage="usage.jsonl").items()}
VERSION = "1.0.0"
SYSTEM = ("Eres un asistente técnico. Responde en español, directo, sin preámbulos ni resúmenes "
          "finales. Si entregas código, solo código con comentarios mínimos.")


class HydraError(Exception):
    def __init__(self, kind, msg, wait=60):
        super().__init__(msg)
        self.kind, self.wait = kind, wait


def _read(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _write(p, data):
    CFG.mkdir(parents=True, exist_ok=True)
    os.chmod(CFG, 0o700)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


def config():
    c = _read(F["prov"], None)
    if c is None:
        c = json.loads((SKILL / "defaults.json").read_text())
        _write(F["prov"], c)
    return c


def save_config(c):
    _write(F["prov"], c)


def secrets_():
    return _read(F["sec"], {})


def set_secret(pid, key):
    s = secrets_()
    if key:
        s[pid] = key
    else:
        s.pop(pid, None)
    _write(F["sec"], s)


def secret(p):
    return secrets_().get(p["id"]) or os.environ.get(p.get("env", ""), "")


def http_json(url, body, headers, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "user-agent": "hydracode/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        msg = e.read()[:300].decode("utf-8", "replace").replace("\n", " ")
        ra = e.headers.get("Retry-After", "")
        if e.code == 429:
            raise HydraError("quota", f"429 {msg}", int(ra) if ra.isdigit() else 3600)
        if e.code in (500, 502, 503, 504):
            raise HydraError("transient", f"{e.code} {msg}", 60)
        if e.code in (401, 403):
            raise HydraError("auth", f"{e.code} {msg}", 900)
        if e.code == 404:
            raise HydraError("model", f"404 {msg}", 3600)
        raise HydraError("other", f"{e.code} {msg}", 300)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if "refused" in str(e).lower():
            raise HydraError("down", "servicio no disponible", 600)
        raise HydraError("transient", str(e)[:200], 60)


def call_openai(p, system, prompt):
    key = secret(p)
    if not key and p.get("need_key", True):
        raise HydraError("auth", "falta la key", 600)
    d = http_json(p["base_url"].rstrip("/") + "/chat/completions",
                  {"model": p["model"], "messages": [{"role": "system", "content": system},
                                                     {"role": "user", "content": prompt}]},
                  {"authorization": "Bearer " + key} if key else {})
    u = d.get("usage") or {}
    try:
        text = d["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HydraError("other", "respuesta sin contenido", 300)
    return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def call_gemini(p, system, prompt):
    key = secret(p)
    if not key:
        raise HydraError("auth", "falta la key", 600)
    d = http_json(f"https://generativelanguage.googleapis.com/v1beta/models/{p['model']}:generateContent",
                  {"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"parts": [{"text": prompt}]}]}, {"x-goog-api-key": key})
    try:
        text = "".join(x.get("text", "") for x in d["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        raise HydraError("other", "respuesta sin contenido", 300)
    u = d.get("usageMetadata") or {}
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def call_cli(p, system, prompt):
    full = f"{system}\n\n{prompt}"
    work = CFG / "cwd"
    work.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([a.replace("{prompt}", full) for a in p["cmd"]], capture_output=True,
                           text=True, timeout=p.get("timeout", 240), stdin=subprocess.DEVNULL,
                           cwd=str(work))
    except FileNotFoundError:
        raise HydraError("auth", "CLI no instalado", 3600)
    except subprocess.TimeoutExpired:
        raise HydraError("transient", "timeout", 120)
    out, err = r.stdout.strip(), (r.stderr or "").strip()
    if r.returncode or not out:
        m = (err or out)[-300:]
        quota = any(w in m.lower() for w in ("usage limit", "quota", "rate limit", "429", "exhausted"))
        raise HydraError("quota" if quota else "other", m or f"rc={r.returncode}", 3600 if quota else 300)
    return out, len(full) // 4, len(out) // 4


CALLS = {"openai": call_openai, "gemini": call_gemini, "cli": call_cli}


def log(pid, role, ok, ti=0, to=0, ms=0, err=""):
    CFG.mkdir(parents=True, exist_ok=True)
    with open(F["usage"], "a") as f:
        f.write(json.dumps(dict(t=int(time.time()), p=pid, role=role, ok=ok, ti=ti, to=to,
                                ms=ms, err=err[:160])) + "\n")


def attempt(p, role, body):
    health = _read(F["health"], {})
    for n in (0, 1):
        t = time.time()
        try:
            text, ti, to = CALLS[p["kind"]](p, SYSTEM, body)
            log(p["id"], role, True, ti, to, int((time.time() - t) * 1000))
            if health.pop(p["id"], None) is not None:
                _write(F["health"], health)
            return text
        except HydraError as e:
            if e.kind == "transient" and n == 0:
                time.sleep(1.5)
                continue
            log(p["id"], role, False, ms=int((time.time() - t) * 1000), err=f"{e.kind}: {e}")
            health = _read(F["health"], {})
            health[p["id"]] = dict(until=time.time() + e.wait, kind=e.kind, msg=str(e)[:200])
            _write(F["health"], health)
            raise


def run(role, prompt, ctx="", private=None):
    c = config()
    r = c["roles"].get(role)
    if not r:
        raise HydraError("all", f"rol desconocido: {role}")
    private = r.get("private", False) if private is None else private
    body = prompt if not ctx else f"{prompt}\n\n<input>\n{ctx}\n</input>"
    trace, health = [], _read(F["health"], {})
    for pid in r["chain"]:
        p = c["providers"].get(pid)
        if not p or not p.get("enabled", True):
            continue
        if private and not p.get("private_ok"):
            trace.append(f"{pid}:privado")
            continue
        h = health.get(pid)
        if h and h["until"] > time.time():
            trace.append(f"{pid}:cooldown")
            continue
        try:
            return attempt(p, role, body), pid
        except HydraError as e:
            trace.append(f"{pid}:{e.kind}")
    raise HydraError("all", "ROUTER_FAILED " + " ".join(trace))


def test(pid):
    p = config()["providers"][pid]
    t = time.time()
    try:
        text = attempt(p, "test", "Responde solo: OK")
        return dict(ok=True, ms=int((time.time() - t) * 1000), text=text.strip()[:80])
    except HydraError as e:
        return dict(ok=False, kind=e.kind, err=str(e)[:200])


def summary():
    c, health = config(), _read(F["health"], {})
    day = datetime.date.today()
    use = {}
    try:
        for ln in open(F["usage"]):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d["p"] not in c["providers"] or d.get("role") == "test":
                continue
            if datetime.date.fromtimestamp(d["t"]) != day:
                continue
            u = use.setdefault(d["p"], dict(calls=0, ok=0, tokens=0, err=""))
            u["calls"] += 1
            u["ok"] += d["ok"]
            u["tokens"] += d["ti"] + d["to"]
            if not d["ok"]:
                u["err"] = d["err"]
    except FileNotFoundError:
        pass
    out = {}
    for pid, p in c["providers"].items():
        u = use.get(pid, dict(calls=0, ok=0, tokens=0, err=""))
        h = health.get(pid)
        u["cooldown"] = h if h and h["until"] > time.time() else None
        u["pct"] = round(100 * u["tokens"] / p["daily_tokens"]) if p.get("daily_tokens") else None
        out[pid] = u
    return out


def status_line():
    parts = []
    for pid, u in summary().items():
        if not config()["providers"][pid].get("enabled", True):
            continue
        if u["cooldown"]:
            parts.append(f"{pid} ⏳{u['cooldown']['kind']}")
        elif u["pct"] is not None:
            parts.append(f"{pid} {u['pct']}%")
        else:
            parts.append(f"{pid} {u['calls']}c")
    return " · ".join(parts)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(f"hydracode {VERSION} · by carlosplata.dev\n" + __doc__.split("\n", 1)[1] + "\n  hydracode status | test <id> | portal [puerto] | roles | --version")
        return 0
    cmd = argv[0]
    if cmd in ("--version", "-V"):
        print(f"hydracode {VERSION} · by carlosplata.dev")
        return 0
    if cmd == "status":
        print(status_line())
    elif cmd == "roles":
        for n, r in config()["roles"].items():
            print(f"{n}{' [privado]' if r.get('private') else ''}: {' → '.join(r['chain'])}")
    elif cmd == "test":
        print(json.dumps(test(argv[1]), ensure_ascii=False))
    elif cmd == "portal":
        sys.path.insert(0, str(SKILL))
        import portal
        portal.serve(int(argv[1]) if len(argv) > 1 else 4190)
    else:
        priv = True if "--private" in argv else None
        args = [a for a in argv[1:] if a != "--private"]
        if not args:
            print('uso: hydracode <rol> "tarea" [--private] [< archivo]', file=sys.stderr)
            return 2
        ctx = "" if sys.stdin.isatty() else sys.stdin.read()
        try:
            text, pid = run(cmd, args[0], ctx, priv)
        except HydraError as e:
            print(e, file=sys.stderr)
            return 1
        print(text.strip())
        print(f"[via {pid}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
