import ast
import json
import re
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


APP = Path(__file__).parents[1] / "app.py"


class SessionLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app_class = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "App")
        wanted = {"_clean_title", "history", "session_flags"}
        cls.methods = {node.name: node for node in app_class.body
                       if isinstance(node, ast.FunctionDef) and node.name in wanted}

    def make_app(self, sessions_dir):
        methods = [self.methods[name] for name in ("_clean_title", "history", "session_flags")
                   if name in self.methods]
        namespace = {
            "SESSIONS_DIR": sessions_dir,
            "json": json,
            "re": re,
            "time": time,
        }
        module = ast.Module(body=methods, type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), namespace)
        return type("AppHarness", (), namespace)()

    def make_session(self, root, sid, **meta):
        session = root / sid
        session.mkdir()
        base = {
            "name": sid,
            "started": "2026-10-03 10:00:00",
            "duration": 60,
            "segments": [{"text": "内容"}],
            "notes": [],
        }
        base.update(meta)
        (session / "session.json").write_text(
            json.dumps(base, ensure_ascii=False), encoding="utf-8")
        return session

    def test_history_exposes_default_and_persisted_collection_flags(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root, "plain")
            self.make_session(root, "marked", favorite=True, archived=True)
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / "transcript.md").write_text("# 老项目\n[00:01] 旧内容\n", encoding="utf-8")

            items = {item["id"]: item for item in self.make_app(root).history()}

            self.assertEqual(
                (items["plain"]["favorite"], items["plain"]["archived"]),
                (False, False),
            )
            self.assertEqual(
                (items["marked"]["favorite"], items["marked"]["archived"]),
                (True, True),
            )
            self.assertEqual(
                (items["legacy"]["favorite"], items["legacy"]["archived"]),
                (False, False),
            )

    def test_session_flags_updates_only_requested_metadata(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.make_session(root, "first", favorite=False, archived=False)
            second = self.make_session(root, "second", favorite=True, archived=False)
            app = self.make_app(root)

            result = app.session_flags(["first", "second"], archived=True)

            self.assertEqual(result, {"ok": True, "updated": 2})
            self.assertEqual(json.loads((first / "session.json").read_text())["archived"], True)
            saved_second = json.loads((second / "session.json").read_text())
            self.assertTrue(saved_second["archived"])
            self.assertTrue(saved_second["favorite"])

    def test_session_flags_rejects_path_traversal(self):
        with TemporaryDirectory() as temp:
            app = self.make_app(Path(temp))
            with self.assertRaisesRegex(RuntimeError, "非法路径"):
                app.session_flags(["../outside"], archived=True)

    def test_post_route_exposes_session_flags_endpoint(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn('if u.path == "/api/session_flags":', source)


if __name__ == "__main__":
    unittest.main()
