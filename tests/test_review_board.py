import ast
import json
import os
import threading
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory


APP = Path(__file__).parents[1] / "app.py"


class ReviewBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app_class = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "App")
        cls.methods = {node.name: node for node in app_class.body
                       if isinstance(node, ast.FunctionDef)}

    def make_app(self, sessions_dir):
        names = ("_read_review", "save_review", "ensure_note_ids")
        namespace = {"SESSIONS_DIR": sessions_dir, "REVIEW_FILE": ".review.json",
                     "REVIEW_MAX_BYTES": 2 * 1024 * 1024, "json": json, "os": os, "uuid": uuid}
        module = ast.Module(body=[self.methods[name] for name in names], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), namespace)
        app = type("AppHarness", (), namespace)()
        app.state = "idle"
        app.lock = threading.RLock()
        return app

    def make_session(self, root, notes):
        d = root / "lecture"
        d.mkdir()
        (d / "session.json").write_text(json.dumps({"duration": 600, "notes": notes}), encoding="utf-8")
        return d

    def test_saved_review_reads_back_and_bad_files_start_empty(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root)
            d = self.make_session(root, [])
            self.assertIsNone(app._read_review(d))
            review = {"version": 1, "items": [{"src": "ch:12", "kind": "chap", "succ": 1}], "days": {"2026-11-05": {"due": 2, "done": 1}}}
            self.assertEqual(app.save_review("lecture", review), {"ok": True})
            self.assertEqual(app._read_review(d), review)
            self.assertEqual([p.name for p in d.iterdir() if p.name.endswith(".tmp")], [])
            (d / ".review.json").write_text("{broken", encoding="utf-8")
            self.assertIsNone(app._read_review(d))

    def test_save_rejects_bad_paths_shapes_and_oversized_state(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root)
            self.make_session(root, [])
            for sid in ("../x", "a/b", ""):
                with self.assertRaises(RuntimeError):
                    app.save_review(sid, {"items": []})
            with self.assertRaises(RuntimeError):
                app.save_review("lecture", {"items": "nope"})
            with self.assertRaises(RuntimeError):
                app.save_review("lecture", {"items": [{"src": "x" * (3 * 1024 * 1024)}]})
            self.assertIsNone(app._read_review(root / "lecture"))

    def test_note_ids_are_stable_and_refuse_stale_snapshots(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root)
            d = self.make_session(root, [{"t": 10.0, "text": "遗忘最快"}, {"t": 20.0, "text": "节省量", "id": "keep"}])
            first = app.ensure_note_ids("lecture", [{"index": 0, "t": 10.0, "text": "遗忘最快"}, {"index": 1, "t": 20.0, "text": "节省量"}])
            self.assertEqual(first["ids"][1], "keep")
            again = app.ensure_note_ids("lecture", [{"index": 0, "t": 10.0, "text": "遗忘最快"}])
            self.assertEqual(again["ids"][0], first["ids"][0])
            saved = json.loads((d / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["notes"][0]["id"], first["ids"][0])
            with self.assertRaises(RuntimeError):
                app.ensure_note_ids("lecture", [{"index": 0, "t": 10.0, "text": "被改过"}])
            app.state = "recording"
            with self.assertRaises(RuntimeError):
                app.ensure_note_ids("lecture", [{"index": 0, "t": 10.0, "text": "遗忘最快"}])

    def test_editing_a_note_keeps_its_review_id(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn('item = {**current, "t": round(timestamp, 1), "text": new}', source)
        self.assertIn('meta["review"] = self._read_review(d)', source)
        self.assertIn('"/api/review_save"', source)
        self.assertIn('"review_master.mp3"', source)


if __name__ == "__main__":
    unittest.main()
