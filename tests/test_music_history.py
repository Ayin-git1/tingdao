import ast
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
import uuid


def history_app(root):
    tree = ast.parse(Path('app.py').read_text())
    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
    wanted = {'_clean_title', '_load_history_cache', '_save_history_cache', 'history_snapshot', 'history'}
    nodes = [n for n in app.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    cls = ast.ClassDef(name='HistoryHarness', bases=[], keywords=[], body=nodes, decorator_list=[])
    ns = dict(json=json, os=os, uuid=uuid, time=time, re=re, SESSIONS_DIR=root,
              HISTORY_CACHE_FILE=root / '.history-cache.json', MASTER_RAW_FILE='master.s16')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), 'app.py', 'exec'), ns)
    result = ns['HistoryHarness']()
    result.HISTORY_CACHE_VERSION = 1
    result._history_cache = {}
    return result


class MusicHistoryTests(unittest.TestCase):
    def test_music_directory_is_not_an_orphan_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / 'music'; music.mkdir()
            (music / 'track.m4a').write_bytes(b'music')
            (music / 'library.json').write_text('{"tracks": []}')
            project = root / 'lecture'; project.mkdir()
            (project / 'session.json').write_text(json.dumps({'name': '课程', 'segments': []}))
            orphan = root / 'stopped-recording'; orphan.mkdir()
            (orphan / 'audio.m4a').write_bytes(b'recording')
            legacy = root / 'legacy'; legacy.mkdir()
            (legacy / 'transcript.md').write_text('# 旧文稿\n[00:01] 内容\n')
            result = history_app(root).history()
            self.assertEqual({item['id'] for item in result}, {'lecture', 'stopped-recording', 'legacy'})
            self.assertEqual((music / 'track.m4a').read_bytes(), b'music')

    def test_stale_music_cache_is_hidden_in_snapshot_and_on_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = {'id': 'music', 'name': 'music', 'stopped': True}
            (root / '.history-cache.json').write_text(json.dumps({'version': 1, 'items': {'music': [1, 2, item]}}))
            app = history_app(root)
            self.assertEqual(app._load_history_cache(), {})
            app._history_cache = {root / 'music' / 'session.json': ((1, 2), item)}
            self.assertEqual(app.history_snapshot(), [])
