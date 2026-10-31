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
import threading
import platform
import subprocess
from unittest.mock import Mock
from test_note_bundle import bundle_code


def load_export_code(sessions_dir):
    tree = ast.parse(Path('app.py').read_text())
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {'_export_safe_name', 'export_bundle_name', 'build_export_zip'}]
    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
    methods = [n for n in app.body if isinstance(n, ast.FunctionDef) and n.name in {'export_sessions', 'pick_save_path'}]
    ns = bundle_code()
    ns.update(dict(platform=platform, subprocess=subprocess, profile_username=lambda:'Ayin', load_setting=lambda k: None, save_setting=lambda *a: None, Path=Path, datetime=datetime, json=json, os=os, re=re, uuid=uuid, zipfile=zipfile,
              SESSIONS_DIR=sessions_dir, NOTE_FILE='note.md', NOTE_IMAGE_DIR='note-images'))
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
    def test_save_dialog_errors_are_not_reported_as_cancellation(self):
        ns = load_export_code(Path('.'))
        ns['platform'] = Mock(system=lambda: 'Darwin')
        ns['subprocess'] = Mock(run=Mock(return_value=Mock(returncode=1, stderr='dialog failed', stdout='')))
        with self.assertRaisesRegex(RuntimeError, 'dialog failed'):
            ns['pick_save_path'](None, '中文.zip')

    def test_save_dialog_uses_system_localization_for_native_controls(self):
        ns = load_export_code(Path('.'))
        ns['platform'] = Mock(system=lambda: 'Darwin')
        runner = Mock(return_value=Mock(returncode=0, stderr='', stdout=''))
        ns['subprocess'] = Mock(run=runner)
        self.assertEqual(ns['pick_save_path'](None, '文稿.zip'), '')
        script = runner.call_args.args[0][4]
        self.assertIn('$.NSLocale.preferredLanguages', script)
        self.assertIn('CFBundleLocalizations', script)
        self.assertIn('CFBundleAllowMixedLocalizations', script)
        self.assertNotIn('AppleLanguages', script)
        self.assertNotIn('panel.prompt =', script)

    def test_bundle_reports_bytes_until_the_file_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_session(root, 's1', '一份')
            ns = load_export_code(root)
            progress = []
            target = root / 'out.zip'
            ns['build_export_zip']([(root / 's1', '一份')], target, 'Ayin', progress=progress.append)
            self.assertEqual(progress[0], 0)
            self.assertGreater(progress[-1], 0)
            self.assertEqual(progress, sorted(progress))
            self.assertTrue(target.is_file())

    def test_default_name_follows_date_rule(self):
        ns = load_export_code(Path('.'))
        now = datetime(2026, 10, 31, 9, 5)
        self.assertEqual(ns['export_bundle_name'](['周会/复盘'], now), '听道文稿_2026-10-31_周会 复盘.zip')
        self.assertEqual(ns['export_bundle_name'](['a', 'b', 'c'], now), '听道文稿_2026-10-31_3份.zip')

    def test_batch_zip_has_complete_documents_and_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'sessions'
            root.mkdir()
            make_session(root, 's1', '同名', note=True, image=True)
            make_session(root, 's2', '同名')
            ns = load_export_code(root)
            target = Path(directory) / 'out'
            picked = []
            harness = type('App', (), {'export_sessions': ns['export_sessions'],
                                       'pick_save_path': lambda self, n: picked.append(n) or str(target),
                                       'state': 'idle', 'session': None, 'progs': {}, 'lock': threading.RLock(), 'note_bundle_lock': threading.Lock()})()
            result = harness.export_sessions(['s1', 's2', 's1'])
            self.assertEqual(result['count'], 2)
            self.assertTrue(picked[0].endswith('_2份.zip'))
            with zipfile.ZipFile(target.with_suffix('.zip')) as zf:
                self.assertEqual(sorted(zf.namelist()), [
                    'tingdao-note.json', '免责声明.txt', '同名/audio.wav', '同名/note-images/a.png',
                    '同名/note.md', '同名/session.json', '同名/transcript.md',
                    '同名（1）/audio.wav', '同名（1）/session.json', '同名（1）/transcript.md'])
            self.assertEqual([p.name for p in Path(directory).iterdir() if p.name.endswith('.part')], [])

    def test_cancel_and_invalid_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_session(root, 's1', '一份')
            ns = load_export_code(root)
            harness = type('App', (), {'export_sessions': ns['export_sessions'],
                                       'pick_save_path': lambda self, n: '', 'state': 'idle',
                                       'session': None, 'progs': {}, 'lock': threading.RLock(), 'note_bundle_lock': threading.Lock()})()
            self.assertEqual(harness.export_sessions(['s1']), {'ok': False, 'cancelled': True})
            for ids in ([], ['..'], ['missing']):
                with self.assertRaises(RuntimeError):
                    harness.export_sessions(ids)


if __name__ == '__main__':
    unittest.main()
