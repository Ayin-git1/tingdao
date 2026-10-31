import ast
import io
import json
import math
import platform
import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).parents[1]
APP = ROOT / "app.py"
INDEX = ROOT / "index.html"


class FrontendBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        handler = next(node for node in tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "Handler")
        method = next(node for node in handler.body
                      if isinstance(node, ast.FunctionDef) and node.name == "do_GET")
        namespace = {
            "json": json,
            "math": math,
            "platform": platform,
            "urlparse": urlparse,
            "INDEX": INDEX,
            "FRONTEND_HTML": None,
            "FRONTEND_PATCHES": None,
            "APP_VERSION": "3.0.0",
            "profile_username": lambda: "Ayin",
            "APP": type("FakeApp", (), {"history_snapshot": lambda self: [
                {"id": "p1", "name": "讲座 </script><b>x</b>", "date": "2026-10-03 10:00"}]})(),
            "load_groups": lambda: {"order": ["课程"], "collapsed": [], "colors": {}},
            "load_setting": lambda key: {
                "appearance": "system",
                "theme_color": {"h": 335.9, "s": 79, "l": 79},
            }.get(key),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(APP), "exec"), namespace)
        cls.do_GET = staticmethod(namespace["do_GET"])
        cls.namespace = namespace

    def render_root(self):
        class Harness:
            path = "/"
            wfile = io.BytesIO()

            def send_response(self, code):
                self.status = code

            def send_header(self, name, value):
                pass

            def end_headers(self):
                pass

        response = Harness()
        self.do_GET(response)
        return response.wfile.getvalue().decode("utf-8")

    def test_history_snapshot_is_injected_and_survives_script_close_in_names(self):
        html = self.render_root()
        self.assertNotIn("__TINGDAO_HISTORY__", html)
        line = next(l for l in html.splitlines() if "bootHistory = JSON.parse(" in l)
        self.assertNotIn("</script>", line)
        literal = re.search(r"JSON\.parse\((\".*\")\);", line).group(1)
        result = subprocess.run(
            ["node", "-e", f"process.stdout.write(JSON.stringify(JSON.parse({literal})))"],
            text=True, capture_output=True, check=True,
        )
        boot = json.loads(result.stdout)
        self.assertEqual(boot["items"][0]["name"], "讲座 </script><b>x</b>")
        self.assertEqual(boot["groups"]["order"], ["课程"])

    def test_pinned_patch_keeps_personalization_and_injects_ready_token(self):
        from types import SimpleNamespace
        self.namespace['FRONTEND_HTML'] = INDEX.read_bytes() + b'<!-- signed patch -->'
        self.namespace['FRONTEND_PATCHES'] = SimpleNamespace(token='ready-token')
        try:
            html = self.render_root()
            self.assertIn('<!-- signed patch -->', html)
            self.assertIn("const token='ready-token'", html)
            self.assertNotIn('__TINGDAO_APPEARANCE__', html)
            self.assertNotIn('__TINGDAO_PATCH_TOKEN__', html)
        finally:
            self.namespace['FRONTEND_HTML'] = None
            self.namespace['FRONTEND_PATCHES'] = None

    def test_root_page_injection_keeps_all_inline_javascript_valid(self):
        class Harness:
            path = "/"
            wfile = io.BytesIO()

            def send_response(self, code):
                self.status = code

            def send_header(self, name, value):
                pass

            def end_headers(self):
                pass

        response = Harness()
        self.do_GET(response)
        self.assertEqual(response.status, 200)
        html = response.wfile.getvalue().decode("utf-8")
        self.assertIn("v3.0.0", html)
        self.assertNotIn("__TINGDAO_VERSION__", html)
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
        self.assertTrue(scripts)
        for index, script in enumerate(scripts, 1):
            result = subprocess.run(
                ["node", "--check", "-"], input=script, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(
                result.returncode, 0,
                f"inline script {index} is invalid:\n{result.stderr}",
            )

    def test_app_version_matches_readme_and_tauri_package_metadata(self):
        app_version = re.search(
            r'^APP_VERSION = "([^"]+)"$', APP.read_text(encoding="utf-8"), re.M
        )
        self.assertIsNotNone(app_version)
        version = app_version.group(1)

        readme_version = re.search(
            r"当前版本：\*\*v([^*]+)\*\*", (ROOT / "README.md").read_text(encoding="utf-8")
        )
        self.assertEqual(version, readme_version.group(1))
        # Tauri/Cargo/npm 只收三段语义版本; 增量版(如 3.1.9.1)对外的版本号由 bundleVersion 与
        # Info.plist 的 CFBundleShortVersionString 承担, 三段部分仍须一致。
        conf = json.loads((ROOT / "tauri-shell" / "tauri.conf.json").read_text(encoding="utf-8"))
        self.assertEqual(version, conf["bundle"]["macOS"]["bundleVersion"])
        version = ".".join(version.split(".")[:3])
        self.assertEqual(version, conf["version"])
        cargo_version = re.search(
            r'^version = "([^"]+)"$',
            (ROOT / "tauri-shell" / "Cargo.toml").read_text(encoding="utf-8"),
            re.M,
        )
        self.assertIsNotNone(cargo_version)
        self.assertEqual(version, cargo_version.group(1))
        for package_file in ("package.json", "package-lock.json"):
            package = json.loads((ROOT / "tauri-shell" / package_file).read_text(encoding="utf-8"))
            self.assertEqual(version, package["version"])


if __name__ == "__main__":
    unittest.main()
