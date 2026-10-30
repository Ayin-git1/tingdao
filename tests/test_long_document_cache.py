import ast
import hashlib
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid
from unittest.mock import patch


class LongDocumentCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        tree = ast.parse(Path('app.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == 'long_document_cache']
        self.assertTrue(nodes, 'long document cache function exists')
        self.ns = dict(CACHE_DIR=self.root / '.cache', json=json, os=os,
                       hashlib=hashlib, uuid=uuid, math=math)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), self.ns)
        self.source = self.root / 'session.json'
        self.meta = dict(duration=7201, summary='summary',
                         segments=[dict(t=20, text='second'), dict(t=0, text='first')],
                         outline=[dict(t=0, level=1, title='chapter')],
                         notes=[dict(t=10, text='note')])
        self.source.write_text(json.dumps(self.meta))

    def cache(self):
        st = self.source.stat()
        return self.ns['long_document_cache'](self.meta, self.source, [st.st_mtime_ns, st.st_size])

    def test_threshold_order_and_reuse(self):
        self.meta['duration'] = 7200
        self.assertIsNone(self.cache())
        self.assertFalse(self.ns['CACHE_DIR'].exists())
        self.meta['duration'] = 7201
        result = self.cache()
        self.assertEqual(result, dict(order=[0, 2, 3, 1], segmentTimes=[0, 20]))
        path = next(self.ns['CACHE_DIR'].glob('long-document-*.json'))
        stamp = path.stat().st_mtime_ns
        self.assertEqual(self.cache(), result)
        self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_source_change_corruption_and_clear_rebuild(self):
        self.cache()
        self.meta['segments'][0]['t'] = 5
        self.source.write_text(json.dumps(self.meta) + ' ')
        self.assertEqual(self.cache()['segmentTimes'], [0, 5])
        path = next(self.ns['CACHE_DIR'].glob('long-document-*.json'))
        saved = json.loads(path.read_text())
        saved['index']['segmentTimes'] = ['broken', {}]
        path.write_text(json.dumps(saved))
        self.assertEqual(self.cache()['segmentTimes'], [0, 5])
        path.write_text('{broken')
        self.assertEqual(self.cache()['order'], [0, 2, 1, 3])
        path.unlink()
        self.assertEqual(self.cache()['order'], [0, 2, 1, 3])
        with patch.object(Path, 'mkdir', side_effect=PermissionError('read only')):
            self.assertEqual(self.cache()['segmentTimes'], [0, 5])

    def test_symlink_cache_root_never_writes_outside(self):
        outside = self.root / 'outside'; outside.mkdir()
        try:
            self.ns['CACHE_DIR'].symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlink unavailable')
        self.assertEqual(self.cache()['order'], [0, 2, 3, 1])
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
