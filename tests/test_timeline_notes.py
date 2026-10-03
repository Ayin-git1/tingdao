import ast
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


APP = Path(__file__).parents[1] / "app.py"


def fmt_ts(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class TimelineNoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app_class = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "App")
        cls.methods = {node.name: node for node in app_class.body
                       if isinstance(node, ast.FunctionDef)}

    def make_app(self, sessions_dir):
        names = ("add_transcript_note", "update_transcript_note",
                 "delete_transcript_note", "_write_md",
                 "note_image_path", "_cleanup_note_assets")
        if any(name not in self.methods for name in names):
            return None
        namespace = {
            "SESSIONS_DIR": sessions_dir,
            "json": json,
            "threading": threading,
            "fmt_ts": fmt_ts,
            "Path": Path,
            "NOTE_IMAGE_DIR": "note-images",
            "NOTE_IMAGE_MIMES": {
                ".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".webp": "image/webp",
            },
        }
        module = ast.Module(body=[self.methods[name] for name in names], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), namespace)
        harness_type = type("AppHarness", (), namespace)
        app = harness_type()
        app.state = "idle"
        app.progs = {}
        app.lock = threading.RLock()
        return app

    def make_session(self, root):
        session_dir = root / "interview-01"
        session_dir.mkdir()
        metadata = {
            "name": "访谈",
            "started": "2026-09-27 10:00:00",
            "duration": 90,
            "segments": [{"t": 20, "text": "原有文稿内容"}],
            "notes": [],
        }
        (session_dir / "session.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        return session_dir, metadata

    def test_completed_session_note_is_persisted_in_meta_and_transcript(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir, _ = self.make_session(root)
            app = self.make_app(root)
            self.assertIsNotNone(app, "App.add_transcript_note is required")
            result = app.add_transcript_note("interview-01", 34, "回访时确认这项需求")

            saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            transcript = (session_dir / "transcript.md").read_text(encoding="utf-8")
            self.assertEqual(result["note"], {"t": 34.0, "text": "回访时确认这项需求"})
            self.assertEqual(saved["notes"], [result["note"]])
            self.assertIn("[00:34] 回访时确认这项需求", transcript)
            self.assertIn("[00:20] 原有文稿内容", transcript)

    def test_completed_session_note_rejects_time_after_recording_duration(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir, _ = self.make_session(root)
            app = self.make_app(root)
            self.assertIsNotNone(app, "App.add_transcript_note is required")

            with self.assertRaisesRegex(RuntimeError, "录音时长"):
                app.add_transcript_note("interview-01", 91, "不能越界")

            saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["notes"], [])
            self.assertFalse((session_dir / "transcript.md").exists())

    def test_completed_session_note_update_sorts_notes_and_rewrites_transcript(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir, _ = self.make_session(root)
            app = self.make_app(root)
            self.assertIsNotNone(app, "App.update_transcript_note is required")
            app.add_transcript_note("interview-01", 34, "要修改的内容")

            result = app.update_transcript_note(
                "interview-01", 0, 34, "要修改的内容", 12, "已经修改")

            saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            transcript = (session_dir / "transcript.md").read_text(encoding="utf-8")
            self.assertEqual(result["note"], {"t": 12.0, "text": "已经修改"})
            self.assertEqual(saved["notes"], [{"t": 12.0, "text": "已经修改"}])
            self.assertIn("[00:12] 已经修改", transcript)
            self.assertNotIn("要修改的内容", transcript)

    def test_completed_session_note_delete_rewrites_transcript_without_touching_segments(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir, _ = self.make_session(root)
            app = self.make_app(root)
            app.add_transcript_note("interview-01", 34, "要删除的内容")

            result = app.delete_transcript_note(
                "interview-01", 0, 34, "要删除的内容")

            saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            transcript = (session_dir / "transcript.md").read_text(encoding="utf-8")
            self.assertEqual(result["notes"], [])
            self.assertEqual(saved["notes"], [])
            self.assertNotIn("要删除的内容", transcript)
            self.assertIn("[00:20] 原有文稿内容", transcript)

    def test_note_update_rejects_stale_index_without_changing_session(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir, _ = self.make_session(root)
            app = self.make_app(root)
            app.add_transcript_note("interview-01", 34, "当前内容")

            with self.assertRaisesRegex(RuntimeError, "已变化"):
                app.update_transcript_note(
                    "interview-01", 0, 34, "旧内容", 12, "不应写入")

            saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["notes"], [{"t": 34.0, "text": "当前内容"}])


if __name__ == "__main__":
    unittest.main()
