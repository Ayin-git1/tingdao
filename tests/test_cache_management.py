import ast
import calendar
from datetime import datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid
import threading
from types import SimpleNamespace
from urllib.parse import urlparse
from io import BytesIO
from unittest.mock import patch


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        tree = ast.parse(Path('app.py').read_text())
        names = {'cache_temp_path', 'cache_info', 'clear_cache', 'check_cache_on_startup', 'migrate_legacy_cache'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.settings = {}
        self.ns = dict(CACHE_DIR=self.root / '.cache', DATA_DIR=self.root,
                       SESSIONS_DIR=self.root, Path=Path, os=os, uuid=uuid,
                       datetime=datetime, calendar=calendar,
                       load_setting=lambda key, default=None: self.settings.get(key, default),
                       save_setting=lambda key, value: self.settings.__setitem__(key, value))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), self.ns)

    def test_size_clear_preserves_originals_and_does_not_follow_links(self):
        cache = self.ns['CACHE_DIR']; cache.mkdir()
        original = self.root / 'recording.wav'; original.write_bytes(b'original')
        (cache / 'work.wav').write_bytes(b'12345')
        (cache / 'outside').symlink_to(original)
        self.assertEqual(self.ns['cache_info']()['bytes'], 5)
        result = self.ns['clear_cache'](datetime(2026, 1, 31))
        self.assertTrue(result['ok'])
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(original.read_bytes(), b'original')
        self.assertEqual(self.settings['cache_last_cleared'], '2026-01-31T00:00:00')

    def test_month_boundary_and_startup_only(self):
        cache = self.ns['CACHE_DIR']; cache.mkdir()
        marker = cache / 'work'; marker.write_bytes(b'work')
        self.settings['cache_last_cleared'] = '2026-01-31T12:00:00'
        self.ns['check_cache_on_startup'](datetime(2026, 2, 28, 11, 59))
        self.assertTrue(marker.exists())
        self.ns['check_cache_on_startup'](datetime(2026, 2, 28, 12))
        self.assertFalse(marker.exists())

    def test_first_launch_cleans_existing_cache(self):
        cache = self.ns['CACHE_DIR']; cache.mkdir()
        (cache / 'old').write_bytes(b'old')
        self.ns['check_cache_on_startup'](datetime(2026, 10, 5))
        self.assertEqual(self.ns['cache_info']()['bytes'], 0)

    def test_legacy_migration_only_moves_known_temporary_files(self):
        session = self.root / 'project'; session.mkdir()
        for name in ('.pretreat.wav', '.whout.json', '.up_m4a.m4a', '.cloud_part0.m4a', 'audio.m4a', 'session.json'):
            (session / name).write_bytes(b'data')
        images = session / 'note-images'; images.mkdir(); (images / 'photo.png').write_bytes(b'image')
        self.ns['migrate_legacy_cache']()
        self.assertFalse((session / '.pretreat.wav').exists())
        self.assertTrue((session / 'audio.m4a').exists())
        self.assertTrue((session / 'session.json').exists())
        self.assertTrue((images / 'photo.png').exists())
        self.assertEqual(self.ns['cache_info']()['bytes'], 16)

    def test_failed_cleanup_keeps_last_success_and_reports_remaining_size(self):
        cache = self.ns['CACHE_DIR']; cache.mkdir()
        locked = cache / 'locked'; locked.write_bytes(b'1234')
        self.settings['cache_last_cleared'] = '2026-01-01T00:00:00'
        unlink = Path.unlink
        def fail(path, *args, **kwargs):
            if path == locked:
                raise PermissionError('locked')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail):
            result = self.ns['clear_cache'](datetime(2026, 10, 5))
        self.assertFalse(result['ok'])
        self.assertEqual(result['bytes'], 4)
        self.assertEqual(self.settings['cache_last_cleared'], '2026-01-01T00:00:00')

    def test_clear_endpoint_protects_active_jobs(self):
        tree = ast.parse(Path('app.py').read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == 'do_POST')
        app = SimpleNamespace(state='idle', progs={'job': {}}, _procs={}, lock=threading.RLock())
        calls = []
        namespace = dict(urlparse=urlparse, json=json, APP=app, clear_cache=lambda: calls.append('clear') or {'ok': True})
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'app.py', 'exec'), namespace)
        request = SimpleNamespace(path='/api/cache/clear', headers={}, rfile=BytesIO(b''), _json=lambda obj, code=200: (obj, code))
        result = namespace['do_POST'](request)
        self.assertEqual(result[1], 409)
        self.assertEqual(calls, [])
        app.progs = {}; app.state = 'recording'
        self.assertEqual(namespace['do_POST'](request)[1], 409)
        app.state = 'idle'
        self.assertEqual(namespace['do_POST'](request)[0], {'ok': True})
        self.assertEqual(calls, ['clear'])

    def test_cache_root_symlink_is_rejected(self):
        outside = self.root / 'outside'; outside.mkdir(); (outside / 'keep').write_bytes(b'keep')
        self.ns['CACHE_DIR'].symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.ns['clear_cache']()
        self.assertTrue((outside / 'keep').exists())

    def test_temporary_names_are_unique_and_centralized(self):
        a = self.ns['cache_temp_path']('upload', '.wav')
        b = self.ns['cache_temp_path']('upload', '.wav')
        self.assertNotEqual(a, b)
        self.assertEqual(a.parent, self.ns['CACHE_DIR'])


if __name__ == '__main__':
    unittest.main()
