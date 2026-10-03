import ast
import json
import math
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


APP = Path(__file__).parents[1] / "app.py"


class TimelineNoteImageMoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app_class = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "App")
        cls.method = next(node for node in app_class.body
                          if isinstance(node, ast.FunctionDef)
                          and node.name == "move_transcript_note_image")

    def make_app(self, root):
        namespace = {
            "SESSIONS_DIR": root,
            "json": json,
            "math": math,
            "threading": threading,
            "NOTE_IMAGE_DIR": "note-images",
        }
        exec(compile(ast.fix_missing_locations(ast.Module(
            body=[self.method], type_ignores=[])), str(APP), "exec"), namespace)
        app = type("AppHarness", (), namespace)()
        app.state = "idle"
        app.progs = {}
        app.lock = threading.RLock()
        app._note_content_text = lambda content: "".join(
            str(node.get("text") or "") for node in content
            if node.get("type") == "text"
        ).strip()
        app._write_md = lambda *args: None
        app._cleanup_note_assets = lambda *args: None
        return app

    def test_saves_only_the_selected_image_canvas_geometry(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session = root / "project"
            image_dir = session / "note-images"
            image_dir.mkdir(parents=True)
            image = image_dir / "image.png"
            image.write_bytes(b"png")
            metadata = {
                "duration": 90,
                "notes": [{
                    "t": 10, "text": "保留的文字",
                    "content": [
                        {"type": "text", "text": "保留的文字"},
                        {"type": "image", "file": "note-images/image.png",
                         "name": "image.png", "mime": "image/png", "width": 10,
                         "height": 10, "displayWidth": 10, "layout": "inline",
                         "position": {"mode": "flow", "x": None, "y": None}},
                    ],
                }],
            }
            session.joinpath("session.json").write_text(
                json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            app = self.make_app(root)

            result = app.move_transcript_note_image(
                "project", 0, 1, 10, "保留的文字", 140, 260, 320
            )

            notes = result["notes"]
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["t"], 10)
            self.assertEqual(notes[0]["text"], "保留的文字")
            self.assertEqual(notes[0]["content"][0], {"type": "text", "text": "保留的文字"})
            image_node = notes[0]["content"][1]
            self.assertEqual(image_node["file"], "note-images/image.png")
            self.assertEqual(image_node["position"], {"mode": "free", "x": 140.0, "y": 260.0})
            self.assertEqual(image_node["displayWidth"], 320)


if __name__ == "__main__":
    unittest.main()
