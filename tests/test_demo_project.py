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
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'seed_demo_project']
        self.settings = {}
        self.written = []
        app = type('App', (), {'_write_md': lambda _self, d, meta, tag: self.written.append((d, tag))})()
        self.ns = dict(SESSIONS_DIR=self.data, DEMO_DIR=DEMO_DIR, NOTE_FILE='note.md',
                       NOTE_IMAGE_DIR='note-images', APP=app, json=json, shutil=shutil, time=time,
                       load_setting=lambda key, default=None: self.settings.get(key, default),
                       save_setting=lambda key, value: self.settings.__setitem__(key, value))
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
        self.assertTrue(self.settings['manual_seeded'])

    def test_existing_libraries_get_it_once(self):
        (self.data / '旧项目-20260101-000000').mkdir()
        sid = self.ns['seed_demo_project']()
        self.assertTrue((self.data / sid / 'session.json').is_file())
        self.assertTrue(self.settings['manual_seeded'])
        shutil.rmtree(self.data / sid)
        self.assertIsNone(self.ns['seed_demo_project']())
        self.assertEqual([p.name for p in self.data.iterdir()], ['旧项目-20260101-000000'])

    def test_skips_libraries_that_already_have_the_manual(self):
        (self.data / '听道使用说明-20261030-120000').mkdir()
        self.assertIsNone(self.ns['seed_demo_project']())
        self.assertEqual(len(list(self.data.iterdir())), 1)

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


if __name__ == '__main__':
    unittest.main()
