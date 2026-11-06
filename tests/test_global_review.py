import ast
import json
import shutil
import sqlite3
from unittest.mock import patch
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class GlobalReviewTests(unittest.TestCase):
    def make_app(self, root):
        tree = ast.parse(Path('app.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        self.assertIn('review_index', methods, 'cross-course review reader is missing')
        namespace = {'SESSIONS_DIR': root, 'REVIEW_FILE': '.review.json', 'json': json, 'to_trash': lambda path: shutil.rmtree(path)}
        module = ast.Module(body=[methods['_read_review'], methods['review_index'], methods['delete_session']], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), 'app.py', 'exec'), namespace)
        app = type('Harness', (), namespace)()
        app._clean_title = lambda name: name
        return app

    def test_index_reads_latest_review_and_omits_archived_and_full_transcript(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for sid, archived in [('a', False), ('b', True), ('none', False)]:
                d = root / sid
                d.mkdir()
                (d / 'session.json').write_text(json.dumps({'name': sid, 'archived': archived, 'duration': 60,
                    'outline': [{'t': 0, 'level': 1, 'title': '章节'}],
                    'notes': [{'id': 'stable', 't': 2, 'text': '笔记'}], 'segments': [{'text': '大量全文'}]}))
                if sid != 'none':
                    (d / '.review.json').write_text(json.dumps({'version': 1, 'items': [{'src': 'note:stable'}], 'days': {}}))
            app = self.make_app(root)
            rows = app.review_index()
            self.assertEqual([r['id'] for r in rows], ['a'])
            self.assertNotIn('segments', rows[0])
            self.assertEqual(rows[0]['notes'][0]['id'], 'stable')
            path = root / 'a' / '.review.json'
            path.write_text(json.dumps({'version': 1, 'items': [], 'days': {'2026-11-06': {'done': 1, 'due': 1}}}))
            self.assertEqual(app.review_index()[0]['review']['items'], [])
            self.assertEqual(app.review_index()[0]['review']['days']['2026-11-06']['done'], 1)

    def test_broken_review_or_session_does_not_hide_other_courses(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for sid in ['good', 'broken-review', 'broken-session']:
                d = root / sid
                d.mkdir()
                (d / 'session.json').write_text('{broken' if sid == 'broken-session' else '{"name":"课件"}')
                (d / '.review.json').write_text('{broken' if sid == 'broken-review' else '{"items":[],"days":{}}')
            self.assertEqual([r['id'] for r in self.make_app(root).review_index()], ['good'])

    def test_app_delete_cleans_projection_only_after_directory_is_gone(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / 'a'
            d.mkdir()
            (d / 'session.json').write_text('{"name":"a"}')
            (d / '.review.json').write_text('{"items":[]}')
            app = self.make_app(root)
            self.assertEqual(len(app.review_index()), 1)
            # Failed trash must preserve the course and its query result.
            namespace = app.delete_session.__func__.__globals__
            with patch.dict(namespace, {'to_trash': lambda path: (_ for _ in ()).throw(OSError('failed'))}):
                with self.assertRaises(OSError):
                    app.delete_session('a', True)
            db = sqlite3.connect(root / '.cache/review-index.sqlite3')
            try:
                self.assertEqual(db.execute('SELECT count(*) FROM courses').fetchone()[0], 1)
            finally:
                db.close()
            self.assertTrue(app.delete_session('a', True)['gone'])
            db = sqlite3.connect(root / '.cache/review-index.sqlite3')
            try:
                self.assertEqual(db.execute('SELECT count(*) FROM courses').fetchone()[0], 0)
            finally:
                db.close()
            self.assertEqual(app.review_index(), [])
