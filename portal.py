"""Portal local de hydracode: conectar proveedores, keys, roles y consumo."""
import base64, hashlib, json, secrets, subprocess, time, urllib.error, urllib.request
from urllib.parse import urlencode, urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hydracode

CSRF = secrets.token_urlsafe(24)
FIELDS = ("id", "label", "kind", "base_url", "model", "env", "cmd", "need_key", "private_ok",
          "enabled", "daily_tokens", "timeout")


def state():
    c = hydracode.config()
    sec = hydracode.secrets_()
    provs = {}
    for pid, p in c["providers"].items():
        provs[pid] = dict(p, has_key=bool(sec.get(pid)), has_env=bool(p.get("env") and hydracode.os.environ.get(p["env"])))
    return dict(providers=provs, roles=c["roles"], usage=hydracode.summary(), services=services(c, sec),
                presets=hydracode._read(hydracode.SKILL / "presets.json", []))


LOGIN = {"codex": (["codex", "login"], ["codex", "login", "status"]),
         "claude": (["claude", "auth", "login"], ["claude", "auth", "status"])}
PORT = 4190
_pkce = {}
_status = {}


def _catalog():
    return hydracode._read(hydracode.SKILL / "catalog.json", [])


def _preset(pid):
    return next((x for x in hydracode._read(hydracode.SKILL / "presets.json", []) if x["id"] == pid), None)


def login_status(name):
    t, old = time.time(), _status.get(name)
    if old and t - old[0] < 20:
        return old[1]
    try:
        r = subprocess.run(LOGIN[name][1], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        out = (r.stdout + r.stderr).lower()
        res = r.returncode == 0 and ("logged in" in out or '"loggedin": true' in out)
    except Exception:
        res = False
    _status[name] = (t, res)
    return res


def ollama_up():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def services(c, sec):
    out = []
    for s in _catalog():
        provs = [c["providers"][x] for x in s["providers"] if x in c["providers"]]
        cd = next((hydracode._read(hydracode.F["health"], {}).get(p["id"]) for p in provs
                   if (hydracode._read(hydracode.F["health"], {}).get(p["id"]) or {}).get("until", 0) > time.time()), None)
        if s["how"] in ("oauth", "key"):
            env = s.get("shared_env") or (_preset(s.get("preset")) or {}).get("env", "")
            ok = any(sec.get(p["id"]) for p in provs) or bool(env and hydracode.os.environ.get(env))
        elif s["how"] == "login":
            ok = login_status(s["login"])
        elif s["how"] == "local":
            ok = ollama_up()
        else:
            ok = None
        out.append(dict(s, connected=ok, cooldown=cd, has_provider=bool(provs)))
    return out


def ensure_provider(sv):
    c = hydracode.config()
    for pid in sv["providers"]:
        if pid in c["providers"]:
            return pid
    pr = _preset(sv["preset"])
    p = {k: v for k, v in pr.items() if k != "name"}
    c["providers"][p["id"]] = p
    hydracode.save_config(c)
    return p["id"]


def autopick_model(pid):
    r = list_models(pid)
    p = hydracode.config()["providers"][pid]
    if not r.get("ok") or not r["models"] or p["model"] in r["models"]:
        return
    prefs = (":free", "llama-3.3-70b", "gpt-oss", "grok-4", "mistral-small", "flash")
    pick = next((m for w in prefs for m in r["models"] if w in m and "embed" not in m), None)
    if pick:
        c = hydracode.config()
        c["providers"][pid]["model"] = pick
        hydracode.save_config(c)


def add_to_roles(pid):
    c = hydracode.config()
    for name in ("leer", "mecanico", "ask"):
        ch = c["roles"].get(name, {}).get("chain")
        if ch is not None and pid not in ch:
            ch.insert(max(len(ch) - 1, 0), pid)
    hydracode.save_config(c)


def finish(sv, key=None):
    pid = ensure_provider(sv)
    if key:
        hydracode.set_secret(pid, key)
    if hydracode.config()["providers"][pid]["kind"] == "openai":
        autopick_model(pid)
    res = hydracode.test(pid)
    if res["ok"]:
        add_to_roles(pid)
    return dict(res, id=pid)


def svc(b):
    return next(s for s in _catalog() if s["id"] == b["service"])


def connect(b):
    sv = svc(b)
    if sv["how"] == "oauth":
        v = secrets.token_urlsafe(48)
        _pkce["v"] = (v, time.time())
        ch = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
        cb = f"http://127.0.0.1:{PORT}/oauth/openrouter"
        return dict(ok=True, open="https://openrouter.ai/auth?" + urlencode(
            dict(callback_url=cb, code_challenge=ch, code_challenge_method="S256")))
    if sv["how"] == "login":
        subprocess.Popen(LOGIN[sv["login"]][0], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        _status.pop(sv["login"], None)
        return dict(ok=True, msg="Se abrió el login en tu navegador; al terminar esta tarjeta se actualiza sola.", poll=True)
    if sv["how"] == "key":
        ensure_provider(sv)
        return dict(ok=True, open=sv["keys_url"], msg="Crea la key, cópiala y pulsa «Pegar y conectar».")
    if sv["how"] == "local":
        ensure_provider(sv)
        return dict(ok=True, open=None if ollama_up() else sv["keys_url"],
                    msg="Ollama activo; usa «Modelos» para elegir uno." if ollama_up() else "Instala Ollama y descarga un modelo (ollama pull qwen2.5-coder).")
    return dict(ok=True, msg="Ejecuta `agy` en la terminal para iniciar sesión.")


def paste(b):
    sv = svc(b)
    key = str(b.get("key", "")).strip()
    if len(key) < 16 or any(ch.isspace() for ch in key):
        return dict(ok=False, kind="clipboard", err="El portapapeles no parece una key; cópiala de nuevo.")
    return finish(sv, key)


def oauth_done(code):
    v = _pkce.pop("v", None)
    if not v or time.time() - v[1] > 600:
        return "No hay un login pendiente (o caducó). Vuelve al portal e inténtalo de nuevo."
    try:
        d = hydracode.http_json("https://openrouter.ai/api/v1/auth/keys",
                            dict(code=code, code_verifier=v[0], code_challenge_method="S256"), {})
        sv = next(s for s in _catalog() if s["id"] == "openrouter")
        finish(sv, d["key"])
    except Exception as e:
        return "No se pudo completar el login: " + str(e)[:150]
    return ""


def list_models(pid):
    p = hydracode.config()["providers"][pid]
    key = hydracode.secret(p)
    if p["kind"] == "gemini":
        url, h = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100", {"x-goog-api-key": key}
    elif p["kind"] == "openai":
        url, h = p["base_url"].rstrip("/") + "/models", ({"authorization": "Bearer " + key} if key else {})
    else:
        return dict(ok=False, err="solo para APIs")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "hydracode/1.0", **h}), timeout=20) as r:
            d = json.load(r)
    except Exception as e:
        return dict(ok=False, err=str(e)[:160])
    ids = [m.get("id") or m.get("name", "").removeprefix("models/") for m in d.get("data", d.get("models", []))]
    return dict(ok=True, models=sorted(i for i in ids if i)[:200])


def upsert(b):
    c = hydracode.config()
    p = {k: b[k] for k in FIELDS if k in b}
    pid = str(p.get("id", "")).strip().lower()
    if not pid or not pid.replace("-", "").replace("_", "").isalnum():
        return dict(ok=False, err="id inválido (letras, números, - y _)")
    if p.get("kind") not in hydracode.CALLS:
        return dict(ok=False, err="tipo inválido")
    if p["kind"] == "cli" and not (isinstance(p.get("cmd"), list) and p["cmd"] and "{prompt}" in "".join(p["cmd"])):
        return dict(ok=False, err="cmd debe ser lista e incluir {prompt}")
    p["id"] = pid
    c["providers"][pid] = {**c["providers"].get(pid, {}), **p}
    hydracode.save_config(c)
    return dict(ok=True)


def delete(pid):
    c = hydracode.config()
    c["providers"].pop(pid, None)
    for r in c["roles"].values():
        r["chain"] = [x for x in r["chain"] if x != pid]
    hydracode.save_config(c)
    hydracode.set_secret(pid, "")
    return dict(ok=True)


def set_role(b):
    c = hydracode.config()
    name = str(b.get("name", "")).strip().lower()
    if not name or not name.isalnum():
        return dict(ok=False, err="nombre de rol inválido")
    chain = [x for x in b.get("chain", []) if x in c["providers"]]
    c["roles"][name] = dict(private=bool(b.get("private")), chain=chain)
    hydracode.save_config(c)
    return dict(ok=True)


def del_role(name):
    c = hydracode.config()
    c["roles"].pop(name, None)
    hydracode.save_config(c)
    return dict(ok=True)


def reset(pid):
    h = hydracode._read(hydracode.F["health"], {})
    h.pop(pid, None)
    hydracode._write(hydracode.F["health"], h)
    return dict(ok=True)


POST = {
    "/api/provider": upsert,
    "/api/secret": lambda b: (hydracode.set_secret(b["id"], b.get("key", "").strip()), dict(ok=True))[1],
    "/api/test": lambda b: hydracode.test(b["id"]),
    "/api/models": lambda b: list_models(b["id"]),
    "/api/delete": lambda b: delete(b["id"]),
    "/api/role": set_role,
    "/api/role-delete": lambda b: del_role(b["name"]),
    "/api/reset": lambda b: reset(b["id"]),
    "/api/connect": connect,
    "/api/paste": paste,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "").rsplit(":", 1)[0] in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", ctype + "; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("x-frame-options", "DENY")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, dict(error="host"))
        if self.path == "/":
            html = (hydracode.SKILL / "portal.html").read_text().replace("__CSRF__", CSRF)
            return self._send(200, html.encode(), "text/html")
        if self.path.startswith("/oauth/openrouter"):
            code = parse_qs(urlparse(self.path).query).get("code", [""])[0]
            err = oauth_done(code) if code else "Falta el código de autorización."
            self.send_response(302)
            self.send_header("location", "/?" + urlencode(dict(oauth="error", msg=err) if err else dict(oauth="ok")))
            self.end_headers()
            return
        if self.path == "/api/state":
            return self._send(200, state())
        self._send(404, dict(error="no existe"))

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if not self._host_ok() or self.headers.get("x-csrf") != CSRF or \
                (origin and origin.split("//")[-1] != self.headers.get("Host")):
            return self._send(403, dict(error="csrf"))
        fn = POST.get(self.path)
        if not fn:
            return self._send(404, dict(error="no existe"))
        try:
            n = int(self.headers.get("content-length", 0))
            b = json.loads(self.rfile.read(min(n, 1_000_000)) or b"{}")
            self._send(200, fn(b))
        except KeyError as e:
            self._send(400, dict(ok=False, err=f"falta {e}"))
        except Exception as e:
            self._send(500, dict(ok=False, err=str(e)[:200]))


def serve(port=4190):
    global PORT
    PORT = port
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"hydracode portal: http://127.0.0.1:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
