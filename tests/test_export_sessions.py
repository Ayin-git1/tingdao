import ast
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
import uuid
import zipfile


def load_export_code(sessions_dir):
    tree = ast.parse(Path('app.py').read_text())
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {'_export_safe_name', 'export_bundle_name', 'build_export_zip'}]
    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
    methods = [n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == 'export_sessions']
    ns = dict(Path=Path, datetime=datetime, json=json, os=os, re=re, uuid=uuid, zipfile=zipfile,
              SESSIONS_DIR=sessions_dir, NOTE_FILE='note.md', NOTE_IMAGE_DIR='note-images')
    exec(compile(ast.Module(body=funcs + methods, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns


def make_session(root, sid, name, note=False, image=False):
    d = root / sid
    d.mkdir()
    (d / 'session.json').write_text(json.dumps({'name': name}), encoding='utf-8')
    (d / 'transcript.md').write_text(f'# {name}\n', encoding='utf-8')
    (d / 'audio.wav').write_bytes(b'audio')
    if note:
        (d / 'note.md').write_text('笔记', encoding='utf-8')
    if image:
        (d / 'note-images').mkdir()
        (d / 'note-images' / 'a.png').write_bytes(b'png')


class ExportSessionsTests(unittest.TestCase):
    def test_default_name_follows_date_rule(self):
        ns = load_export_code(Path('.'))
        now = datetime(2026, 10, 31, 9, 5)
        self.assertEqual(ns['export_bundle_name'](['周会/复盘'], now), '听道文稿_2026-10-31_周会 复盘.zip')
        self.assertEqual(ns['export_bundle_name'](['a', 'b', 'c'], now), '听道文稿_2026-10-31_3份.zip')

    def test_batch_zip_has_one_folder_per_document_without_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'sessions'
            root.mkdir()
            make_session(root, 's1', '同名', note=True, image=True)
            make_session(root, 's2', '同名')
            ns = load_export_code(root)
            target = Path(directory) / 'out'
            picked = []
            harness = type('App', (), {'export_sessions': ns['export_sessions'],
                                       'pick_save_path': lambda self, n: picked.append(n) or str(target)})()
            result = harness.export_sessions(['s1', 's2', 's1'])
            self.assertEqual(result['count'], 2)
            self.assertTrue(picked[0].endswith('_2份.zip'))
            with zipfile.ZipFile(target.with_suffix('.zip')) as zf:
                self.assertEqual(sorted(zf.namelist()), [
                    '同名 (2)/同名.md', '同名/note-images/a.png', '同名/同名.md', '同名/课后笔记.md'])
            self.assertEqual([p.name for p in Path(directory).iterdir() if p.name.endswith('.part')], [])

    def test_cancel_and_invalid_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_session(root, 's1', '一份')
            ns = load_export_code(root)
            harness = type('App', (), {'export_sessions': ns['export_sessions'],
                                       'pick_save_path': lambda self, n: ''})()
            self.assertEqual(harness.export_sessions(['s1']), {'ok': False, 'cancelled': True})
            for ids in ([], ['..'], ['missing']):
                with self.assertRaises(RuntimeError):
                    harness.export_sessions(ids)


if __name__ == '__main__':
    unittest.main()
