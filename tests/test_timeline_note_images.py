import ast
import base64
import json
import threading
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory


APP = Path(__file__).parents[1] / "app.py"
PNG_BYTES = b"\x89PNG\r\n\x1a\nimage-data"


def fmt_ts(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class TimelineNoteImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app_class = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "App")
        cls.methods = {node.name: node for node in app_class.body
                       if isinstance(node, ast.FunctionDef)}

    def make_app(self, sessions_dir):
        names = (
            "note", "add_transcript_note", "update_transcript_note",
            "delete_transcript_note", "_write_md", "note_image_path",
            "read_note_image_file",
            "_note_content_text", "_materialize_note_content",
            "_cleanup_note_assets",
        )
        if any(name not in self.methods for name in names):
            return None
        if "delete_recording_image" in self.methods:
            names += ("delete_recording_image",)
        namespace = {
            "SESSIONS_DIR": sessions_dir, "SR": 16000,
            "json": json,
            "threading": threading,
            "fmt_ts": fmt_ts,
            "base64": base64,
            "Path": Path,
            "uuid": uuid,
            "NOTE_IMAGE_DIR": "note-images",
            "MAX_NOTE_IMAGE_BYTES": 20 * 1024 * 1024,
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

    def test_recording_image_note_uses_live_time_and_fixed_layout(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root)
            directory = self.make_session(root)
            app.session = {"dir": directory, "notes": []}
            app.total_samples = 32000
            events = []
            app.emit = lambda **event: events.append(event)
            for state in ("recording", "paused"):
                app.state = state
                content = self.image_content(state)
                content[1]["layout"] = "aside-right"
                note = app.note("", content, self.assets(state))
                self.assertEqual(note["t"], 2)
                self.assertEqual(note["content"][1]["layout"], "inline")
                self.assertTrue((directory / note["content"][1]["file"]).is_file())
                self.assertEqual(events[-1]["id"], directory.name)
            self.assertEqual(len(app.session["notes"]), 2)
            app.state = "stopping"
            with self.assertRaises(RuntimeError):
                app.note("", self.image_content("stop"), self.assets("stop"))

    def test_recording_image_keeps_captured_time_and_deletion(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root)
            directory = self.make_session(root)
            app.session = {"dir": directory, "notes": []}
            app.state = "recording"
            app.total_samples = 160000
            events = []
            app.emit = lambda **event: events.append(event)
            note = app.note("", self.image_content("capture"), self.assets("capture"),
                            t=5, sid=directory.name)
            self.assertEqual(note["t"], 5)
            self.assertEqual(note["content"][1]["displayWidth"], 86)
            image = note["content"][1]["file"]
            app.delete_recording_image(directory.name, image)
            self.assertFalse(any(node.get("type") == "image" for node in note["content"]))
            self.assertFalse((directory / image).exists())
            with self.assertRaises(RuntimeError):
                app.note("", self.image_content("wrong"), self.assets("wrong"), t=5, sid="other")
            with self.assertRaises(RuntimeError):
                app.note("", self.image_content("future"), self.assets("future"), t=999, sid=directory.name)

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
        return session_dir

    def image_content(self, *asset_ids):
        content = [{"type": "text", "text": "图片前"}]
        for index, asset_id in enumerate(asset_ids):
            content.append({
                "type": "image", "asset": asset_id,
                "name": f"IMG_{index + 1}.png", "mime": "image/png",
                "width": 640, "height": 480, "displayWidth": 260,
                "layout": "inline",
                "position": {"mode": "flow", "x": None, "y": None},
            })
            content.append({"type": "text", "text": f"图片{index + 1}后"})
        return content

    def assets(self, *asset_ids):
        encoded = base64.b64encode(PNG_BYTES).decode("ascii")
        return [{
            "id": asset_id, "name": f"{asset_id}.png",
            "mime": "image/png", "data": encoded,
        } for asset_id in asset_ids]

    def test_aside_anchor_and_inline_position_survive_saved_session(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir = self.make_session(root)
            app = self.make_app(root)
            for layout in ("aside-left", "aside-right", "inline"):
                content = self.image_content("asset-1")
                content[1].update(layout=layout, anchorRowId="segment-2", insertPosition="before")
                result = app.add_transcript_note("interview-01", 34, "", content, self.assets("asset-1"))
                image = result["note"]["content"][1]
                self.assertEqual(image["layout"], layout)
                self.assertEqual(image["anchorRowId"], "segment-2")
                self.assertEqual(image["insertPosition"], "before")
                saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["notes"][-1]["content"][1], image)

    def test_moving_existing_image_persists_new_anchor_without_reupload(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir = self.make_session(root)
            app = self.make_app(root)
            created = app.add_transcript_note(
                "interview-01", 34, "", self.image_content("asset-1"), self.assets("asset-1"))
            note = created["note"]
            content = note["content"]
            original_file = content[1]["file"]
            content[1].update(layout="aside-right", anchorRowId="segment-5", insertPosition="after")
            app.update_transcript_note(
                "interview-01", 0, note["t"], note["text"], note["t"], note["text"], content, [])
            saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            image = saved["notes"][0]["content"][1]
            self.assertEqual(image["anchorRowId"], "segment-5")
            self.assertEqual(image["layout"], "aside-right")
            self.assertEqual(image["file"], original_file)
            self.assertTrue((session_dir / original_file).is_file())

    def test_add_note_materializes_multiple_images_and_preserves_mixed_order(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir = self.make_session(root)
            app = self.make_app(root)
            self.assertIsNotNone(app, "image-aware App helpers are required")

            result = app.add_transcript_note(
                "interview-01", 34, "图片前图片1后图片2后",
                self.image_content("asset-1", "asset-2"),
                self.assets("asset-1", "asset-2"),
            )

            note = result["note"]
            saved = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
            image_dir = session_dir / "note-images"
            self.assertEqual(note["text"], "图片前图片1后图片2后")
            self.assertEqual([node["type"] for node in note["content"]],
                             ["text", "image", "text", "image", "text"])
            self.assertEqual(len(list(image_dir.iterdir())), 2)
            self.assertEqual(saved["notes"], [note])
            self.assertTrue(all((session_dir / node["file"]).is_file()
                                for node in note["content"] if node["type"] == "image"))
            transcript = (session_dir / "transcript.md").read_text(encoding="utf-8")
            self.assertIn("![IMG_1.png](note-images/", transcript)
            self.assertIn("![IMG_2.png](note-images/", transcript)

    def test_update_removes_unreferenced_image_and_legacy_text_note_still_works(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session_dir = self.make_session(root)
            app = self.make_app(root)
            created = app.add_transcript_note(
                "interview-01", 34, "图片前图片1后",
                self.image_content("asset-1"), self.assets("asset-1"))
            image_file = next((session_dir / "note-images").iterdir())

            result = app.update_transcript_note(
                "interview-01", 0, 34, "图片前图片1后", 12, "已经修改",
                [{"type": "text", "text": "已经修改"}], [])

            self.assertEqual(result["note"]["text"], "已经修改")
            self.assertFalse(image_file.exists())
            self.assertEqual(list((session_dir / "note-images").iterdir()), [])

            legacy = app.add_transcript_note("interview-01", 20, "旧格式笔记")
            self.assertEqual(legacy["note"]["text"], "旧格式笔记")

    def test_rejects_invalid_asset_and_note_image_paths(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root)
            app = self.make_app(root)

            bad_content = [{
                "type": "image", "asset": "bad", "name": "bad.svg",
                "mime": "image/svg+xml", "width": 1, "height": 1,
                "displayWidth": 1, "layout": "inline",
            }]
            bad_asset = [{"id": "bad", "name": "bad.svg",
                          "mime": "image/svg+xml", "data": "eA=="}]
            with self.assertRaisesRegex(RuntimeError, "图片类型"):
                app.add_transcript_note("interview-01", 10, "", bad_content, bad_asset)

            with self.assertRaisesRegex(RuntimeError, "图片路径"):
                app.note_image_path("interview-01", "../outside.png")

    def test_rejects_image_larger_than_20_mib(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root)
            app = self.make_app(root)
            content = [{"type": "image", "asset": "large", "name": "large.png",
                        "mime": "image/png", "width": 1, "height": 1,
                        "displayWidth": 1, "layout": "inline"}]
            large = base64.b64encode(b"x" * (20 * 1024 * 1024 + 1)).decode("ascii")
            with self.assertRaisesRegex(RuntimeError, "过大"):
                app.add_transcript_note(
                    "interview-01", 10, "", content,
                    [{"id": "large", "name": "large.png",
                      "mime": "image/png", "data": large}],
                )

    def test_reads_native_dragged_image_path_as_frontend_asset(self):
        with TemporaryDirectory() as temp:
            image = Path(temp) / "拖入.png"
            image.write_bytes(PNG_BYTES)
            app = self.make_app(Path(temp) / "sessions")

            result = app.read_note_image_file(str(image))

            self.assertEqual(result["name"], "拖入.png")
            self.assertEqual(result["mime"], "image/png")
            self.assertEqual(base64.b64decode(result["data"]), PNG_BYTES)

            image.with_suffix(".svg").write_bytes(PNG_BYTES)
            with self.assertRaisesRegex(RuntimeError, "仅支持"):
                app.read_note_image_file(str(image.with_suffix(".svg")))


if __name__ == "__main__":
    unittest.main()
