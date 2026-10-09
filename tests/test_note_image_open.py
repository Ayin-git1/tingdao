import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


class NoteImageOpenTests(unittest.TestCase):
    def test_open_saved_image_and_reject_invalid_paths(self):
        tree = ast.parse(Path('app.py').read_text())
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = [n for n in app.body if isinstance(n, ast.FunctionDef)
                   and n.name in {'note_image_path', 'open_note_image'}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'session' / 'note-images'
            folder.mkdir(parents=True)
            image = folder / '原图.png'
            image.write_bytes(b'image')
            process = Mock()
            platform = Mock()
            platform.system.return_value = 'Darwin'
            ns = dict(Path=Path, SESSIONS_DIR=root, NOTE_IMAGE_DIR='note-images',
                      NOTE_IMAGE_MIMES={'.png': 'image/png'}, platform=platform,
                      subprocess=process, os=Mock())
            exec(compile(ast.Module(body=methods, type_ignores=[]), 'app.py', 'exec'), ns)
            harness = type('App', (), {n.name: ns[n.name] for n in methods})()
            self.assertEqual(harness.open_note_image('session', 'note-images/原图.png'), {'ok': True})
            process.Popen.assert_called_once_with(['open', str(image.resolve())])
            for sid, file in [('..', 'note-images/原图.png'), ('session', '../原图.png'),
                              ('session', 'note-images/missing.png')]:
                with self.assertRaises(RuntimeError):
                    harness.open_note_image(sid, file)
            self.assertEqual(process.Popen.call_count, 1)
