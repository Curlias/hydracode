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


if __name__ == "__main__":
    unittest.main()
