import ast
import json
import shutil
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

DEMO_DIR = Path('assets/demo')


class DemoProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        tree = ast.parse(Path('app.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('seed_demo_project', 'seed_first_open_guide')]
        self.settings = {}
        self.written = []
        app = type('App', (), {'_write_md': lambda _self, d, meta, tag: self.written.append((d, tag))})()
        self.ns = dict(SESSIONS_DIR=self.data, DEMO_DIR=DEMO_DIR, NOTE_FILE='note.md',
                       NOTE_IMAGE_DIR='note-images', APP=app, json=json, platform=self, shutil=shutil, time=time,
                       load_setting=lambda key, default=None: self.settings.get(key, default),
                       save_setting=lambda key, value: self.settings.__setitem__(key, value))
        self.system_name = 'Darwin'
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), self.ns)

    def test_first_launch_places_a_complete_demo_project(self):
        (self.data / '.cache').mkdir()
        sid = self.ns['seed_demo_project']()
        d = self.data / sid
        meta = json.loads((d / 'session.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['name'], '听道使用说明')
        self.assertTrue((d / meta['audio']).is_file())
        self.assertTrue((d / 'note.md').is_file())
        for note in meta['notes']:
            for node in note.get('content') or []:
                if node['type'] == 'image':
                    self.assertTrue((d / node['file']).is_file(), node['file'])
        self.assertEqual(self.written, [(d, '使用说明')])
        self.assertTrue(self.settings['demo_seeded'])

    def test_runs_once_and_skips_existing_libraries(self):
        (self.data / '旧项目-20260101-000000').mkdir()
        self.assertIsNone(self.ns['seed_demo_project']())
        self.assertTrue(self.settings['demo_seeded'])
        shutil.rmtree(self.data / '旧项目-20260101-000000')
        self.assertIsNone(self.ns['seed_demo_project']())
        self.assertEqual([p.name for p in self.data.iterdir()], [])

    def test_demo_text_is_consistent(self):
        meta = json.loads((DEMO_DIR / 'demo-session.json').read_text(encoding='utf-8'))
        segs = meta['segments']
        self.assertEqual([s['t'] for s in segs], sorted(s['t'] for s in segs))
        self.assertLessEqual(segs[-1]['t'], meta['duration'])
        self.assertEqual(meta['outline'][0]['level'], 1)
        for seg in segs:
            length = len(seg['text'].encode('utf-16-le')) // 2
            for fmt in seg.get('formats', []):
                self.assertTrue(0 <= fmt['start'] < fmt['end'] <= length)

    def system(self):
        return self.system_name

    def test_first_open_guide_is_added_once_even_for_existing_libraries(self):
        (self.data / '旧项目-20260101-000000').mkdir()
        sid = self.ns['seed_first_open_guide']()
        meta = json.loads((self.data / sid / 'session.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['name'], '首次打开说明')
        self.assertIsNone(meta['audio'])
        self.assertTrue(any('仍要打开' in s['text'] for s in meta['segments']))
        self.assertEqual(self.written, [(self.data / sid, '使用说明')])
        shutil.rmtree(self.data / sid)
        self.assertIsNone(self.ns['seed_first_open_guide']())
        self.assertEqual([p.name for p in self.data.iterdir()], ['旧项目-20260101-000000'])

    def test_first_open_guide_is_mac_only(self):
        self.system_name = 'Windows'
        self.assertIsNone(self.ns['seed_first_open_guide']())
        self.assertEqual(list(self.data.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
