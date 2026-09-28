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
            "APP_VERSION": "2.7.10",
            "load_setting": lambda key: {
                "appearance": "system",
                "theme_color": {"h": 335.9, "s": 79, "l": 79},
            }.get(key),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(APP), "exec"), namespace)
        cls.do_GET = staticmethod(namespace["do_GET"])

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
        self.assertIn("v2.7.10", html)
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
        self.assertEqual(
            version,
            json.loads((ROOT / "tauri-shell" / "tauri.conf.json").read_text(encoding="utf-8"))["version"],
        )


if __name__ == "__main__":
    unittest.main()
