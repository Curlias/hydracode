import os, sys, tempfile, unittest, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ["HYDRACODE_HOME"] = tempfile.mkdtemp()
import hydracode as h


def cli(code, **kw):
    return dict(kind="cli", cmd=["python3", "-c", code, "{prompt}"], **kw)


class Fallback(unittest.TestCase):
    def setUp(self):
        for f in h.F.values():
            f.unlink(missing_ok=True)
        h.save_config({"providers": {
            "q": dict(id="q", **cli("import sys;sys.stderr.write('usage limit');sys.exit(1)")),
            "pub": dict(id="pub", **cli("print('PUB')", private_ok=False)),
            "ok": dict(id="ok", **cli("print('LISTO')", private_ok=True))},
            "roles": {"x": {"chain": ["q", "ok"]}, "p": {"private": True, "chain": ["pub", "q", "ok"]}}})

    def test_quota_falls_to_next_and_pauses(self):
        self.assertEqual(h.run("x", "hola")[1], "ok")
        self.assertEqual(h.summary()["q"]["cooldown"]["kind"], "quota")
        self.assertEqual(h.run("x", "hola")[1], "ok")
        self.assertEqual(h.summary()["q"]["calls"], 1)

    def test_private_skips_non_private(self):
        self.assertEqual(h.run("p", "hola")[1], "ok")
        self.assertEqual(h.summary()["pub"]["calls"], 0)

    def test_all_fail(self):
        with self.assertRaises(h.HydraError):
            h.run("zzz", "a")

    def test_secrets_file_is_private(self):
        h.set_secret("q", "k" * 20)
        self.assertEqual(oct(os.stat(h.F["sec"]).st_mode)[-3:], "600")


class Ram(unittest.TestCase):
    def test_free_gb_is_positive(self):
        self.assertGreater(h.free_gb(), 0)

    def test_low_ram_skips_local_model(self):
        h.save_config({"providers": {"loc": dict(id="loc", kind="ollama", model="m", need_key=False,
                       base_url="http://127.0.0.1:9", min_free_gb=10**6)}, "roles": {}})
        with self.assertRaises(h.HydraError) as cm:
            h.attempt(h.config()["providers"]["loc"], "x", "hola")
        self.assertEqual(cm.exception.kind, "lowram")


class Bar(unittest.TestCase):
    def test_bar_renders_two_lines_without_crashing(self):
        h.save_config({"providers": {"ok": dict(id="ok", **cli("print(1)"))}, "roles": {}})
        out = h.bar('{"model":{"display_name":"Sonnet"},"context_window":{"used_percentage":34}}')
        plain = __import__("re").sub(r"\x1b\[[0-9;]*m", "", out)
        self.assertEqual(len(plain.splitlines()), 2)
        self.assertIn("ctx", plain)
        self.assertIn("34%", plain)

    def test_bar_survives_empty_input(self):
        self.assertIn("hydracode", h.bar(""))


if __name__ == "__main__":
    unittest.main()
