import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from review_index import read_index, remove_course


class IndexCacheTests(unittest.TestCase):
    def course(self, root, sid='a'):
        d = root / sid
        d.mkdir()
        (d / 'session.json').write_text(json.dumps({'name': sid, 'notes': [], 'segments': ['large']}))
        (d / '.review.json').write_text('{"items":[],"days":{}}')
        return d

    def test_projection_keeps_formatted_sources_without_full_transcript(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = self.course(root)
            segment = {'t': 12, 'text': '划线', 'formats': [
                {'start': 0, 'end': 2, 'style': {'underline': True}}]}
            (d / 'session.json').write_text(json.dumps({'segments': [
                {'t': 0, 'text': '不需要的全文'}, segment]}))
            row = read_index(root, str)[0]
            self.assertNotIn('segments', row)
            self.assertEqual(row['reviewSegments'], [segment])
            self.assertEqual(read_index(root, str)[0]['reviewSegments'], [segment])

    def test_incremental_sidecar_deletion_and_rebuild(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = self.course(root)
            self.assertEqual(len(read_index(root, str)), 1)
            with patch.object(Path, 'read_text', side_effect=AssertionError('warm read reparsed source')):
                self.assertEqual(len(read_index(root, str)), 1)
            (d / '.review.json').write_text('{"items":[{"src":"new"}],"days":{}}')
            self.assertEqual(read_index(root, str)[0]['review']['items'], [{'src': 'new'}])
            (root / '.cache/review-index.sqlite3').unlink()
            self.assertEqual(len(read_index(root, str)), 1)
            shutil.rmtree(d)
            self.assertEqual(read_index(root, str), [])
            db = sqlite3.connect(root / '.cache/review-index.sqlite3')
            try:
                self.assertEqual(db.execute('select count(*) from courses').fetchone()[0], 0)
            finally:
                db.close()

    def test_metadata_archive_and_missing_sidecar_refresh(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = self.course(root)
            self.assertEqual(read_index(root, str)[0]['name'], 'a')
            (d / 'session.json').write_text('{"name":"renamed","notes":[{"id":"new"}]}')
            row = read_index(root, str)[0]
            self.assertEqual(row['name'], 'renamed')
            self.assertEqual(row['notes'], [{'id': 'new'}])
            self.assertNotIn('segments', row)
            (d / 'session.json').write_text('{"archived":true}')
            self.assertEqual(read_index(root, str), [])
            (d / 'session.json').write_text('{"name":"restored"}')
            self.assertEqual(len(read_index(root, str)), 1)
            (d / '.review.json').unlink()
            self.assertEqual(read_index(root, str), [])

    def test_sql_failure_and_broken_sources_are_isolated(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.course(root)
            d = self.course(root, 'broken')
            (d / 'session.json').write_text('{broken')
            with patch('review_index.sqlite3.connect', side_effect=sqlite3.OperationalError('locked')):
                self.assertEqual([x['id'] for x in read_index(root, str)], ['a'])
            self.assertEqual([x['id'] for x in read_index(root, str)], ['a'])
            (root / '.cache/review-index.sqlite3').write_bytes(b'broken database')
            self.assertEqual([x['id'] for x in read_index(root, str)], ['a'])

    def test_thousand_courses_cold_and_warm(self):
        import time
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(1000):
                d = self.course(root, f'course-{i:04}')
                (d / 'session.json').write_text(json.dumps({
                    'name': d.name, 'outline': [{'t': 0, 'title': '章节'}],
                    'notes': [{'id': 'n', 'text': '笔记'}],
                    'segments': [{'text': '课文' * 1000}] * 10}))
            start = time.perf_counter()
            self.assertEqual(len(read_index(root, str)), 1000)
            cold = time.perf_counter() - start
            start = time.perf_counter()
            with patch.object(Path, 'read_text', side_effect=AssertionError('warm source read')):
                self.assertEqual(len(read_index(root, str)), 1000)
            warm = time.perf_counter() - start
            print(f'\n1000 courses: cold={cold:.3f}s warm={warm:.3f}s')

    def test_eviction_does_not_create_cache_and_ignores_sql_failure(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            remove_course(root, 'missing')
            self.assertFalse((root / '.cache').exists())
            self.course(root)
            read_index(root, str)
            with patch('review_index.sqlite3.connect', side_effect=sqlite3.OperationalError('locked')):
                remove_course(root, 'a')
            self.assertEqual(len(read_index(root, str)), 1)
