import ast
import json
import plistlib
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).parents[1]
APP = ROOT / "app.py"
PLIST = ROOT / "tauri-shell" / "Info.plist"


class MacOSDataAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        handler = next(node for node in tree.body
                       if isinstance(node, ast.ClassDef) and node.name == "Handler")
        method = next(node for node in handler.body
                      if isinstance(node, ast.FunctionDef) and node.name == "do_GET")
        namespace = {
            "json": json,
            "urlparse": urlparse,
            "APP": type("App", (), {
                "history": lambda self: (_ for _ in ()).throw(
                    PermissionError("Operation not permitted")),
            })(),
        }
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(APP), "exec"), namespace)
        cls.do_GET = staticmethod(namespace["do_GET"])

    def test_macos_bundle_declares_documents_folder_usage(self):
        plist = plistlib.loads(PLIST.read_bytes())
        self.assertIn("NSDocumentsFolderUsageDescription", plist)
        self.assertTrue(plist["NSDocumentsFolderUsageDescription"])

    def test_history_permission_failure_is_a_structured_actionable_response(self):
        class Harness:
            path = "/api/history"

            def _json(self, payload, code=200):
                self.response = payload, code

        response = Harness()
        self.do_GET(response)
        payload, code = response.response
        self.assertEqual(code, 403)
        self.assertEqual(payload["code"], "data_access_denied")
        self.assertIn("系统设置", payload["error"])


if __name__ == "__main__":
    unittest.main()
