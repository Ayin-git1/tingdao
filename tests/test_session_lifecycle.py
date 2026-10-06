import ast
import json
import os
import re
import shutil
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor


APP = Path(__file__).parents[1] / "app.py"


class SessionLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app_class = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "App")
        wanted = {"_clean_title", "history", "session_flags"}
        cls.methods = {node.name: node for node in app_class.body
                       if isinstance(node, ast.FunctionDef) and node.name in wanted}

    def make_app(self, sessions_dir):
        methods = [self.methods[name] for name in ("_clean_title", "history", "session_flags")
                   if name in self.methods]
        namespace = {
            "SESSIONS_DIR": sessions_dir,
            "json": json,
            "re": re,
            "time": time,
            "MASTER_RAW_FILE": "master.s16",
        }
        module = ast.Module(body=methods, type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), namespace)
        app = type("AppHarness", (), namespace)()
        app._history_cache = {}
        return app

    def make_session(self, root, sid, **meta):
        session = root / sid
        session.mkdir()
        base = {
            "name": sid,
            "started": "2026-10-03 10:00:00",
            "duration": 60,
            "segments": [{"text": "内容"}],
            "notes": [],
        }
        base.update(meta)
        (session / "session.json").write_text(
            json.dumps(base, ensure_ascii=False), encoding="utf-8")
        return session

    def test_history_exposes_default_and_persisted_collection_flags(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root, "plain")
            self.make_session(root, "marked", favorite=True, archived=True)
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / "transcript.md").write_text("# 老项目\n[00:01] 旧内容\n", encoding="utf-8")

            items = {item["id"]: item for item in self.make_app(root).history()}

            self.assertEqual(
                (items["plain"]["favorite"], items["plain"]["archived"]),
                (False, False),
            )
            self.assertEqual(
                (items["marked"]["favorite"], items["marked"]["archived"]),
                (True, True),
            )
            self.assertEqual(
                (items["legacy"]["favorite"], items["legacy"]["archived"]),
                (False, False),
            )

    def test_session_flags_updates_only_requested_metadata(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.make_session(root, "first", favorite=False, archived=False)
            second = self.make_session(root, "second", favorite=True, archived=False)
            app = self.make_app(root)

            result = app.session_flags(["first", "second"], archived=True)

            self.assertEqual(result, {"ok": True, "updated": 2})
            self.assertEqual(json.loads((first / "session.json").read_text())["archived"], True)
            saved_second = json.loads((second / "session.json").read_text())
            self.assertTrue(saved_second["archived"])
            self.assertTrue(saved_second["favorite"])

    def test_session_flags_rejects_path_traversal(self):
        with TemporaryDirectory() as temp:
            app = self.make_app(Path(temp))
            with self.assertRaisesRegex(RuntimeError, "非法路径"):
                app.session_flags(["../outside"], archived=True)

    def test_post_route_exposes_session_flags_endpoint(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn('if u.path == "/api/session_flags":', source)

    def count_json_reads(self, app):
        reads = []
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path.name == 'session.json':
                reads.append(path)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            items = app.history()
        return items, reads

    def test_unchanged_history_does_not_read_json_again(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root, 'first')
            self.make_session(root, 'second')
            app = self.make_app(root)
            initial, reads = self.count_json_reads(app)
            self.assertEqual(len(reads), 2)
            again, reads = self.count_json_reads(app)
            self.assertEqual(again, initial)
            self.assertEqual(reads, [])

    def test_file_mtime_invalidates_cache_even_when_size_and_directory_mtime_match(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session = self.make_session(root, 'first', name='Alpha')
            sj = session / 'session.json'
            app = self.make_app(root)
            app.history()
            before = sj.stat()
            directory_mtime = session.stat().st_mtime_ns
            sj.write_text(sj.read_text().replace('Alpha', 'Bravo'), encoding='utf-8')
            os.utime(sj, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            self.assertEqual(sj.stat().st_size, before.st_size)
            self.assertEqual(session.stat().st_mtime_ns, directory_mtime)
            items, reads = self.count_json_reads(app)
            self.assertEqual(items[0]['name'], 'Bravo')
            self.assertEqual(reads, [sj])

    def test_size_invalidates_cache_even_when_mtime_matches(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            sj = self.make_session(root, 'first') / 'session.json'
            app = self.make_app(root)
            app.history()
            before = sj.stat()
            meta = json.loads(sj.read_text())
            meta['notes'] = [{'text':'added note'}]
            sj.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
            os.utime(sj, ns=(before.st_atime_ns, before.st_mtime_ns))
            items, reads = self.count_json_reads(app)
            self.assertEqual(items[0]['notes'], 1)
            self.assertEqual(reads, [sj])

    def test_changed_project_only_reloads_its_own_json(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.make_session(root, 'first')
            self.make_session(root, 'second')
            app = self.make_app(root)
            app.history()
            app.session_flags(['first'], favorite=True, archived=True)
            items, reads = self.count_json_reads(app)
            self.assertEqual(reads, [first / 'session.json'])
            item = next(item for item in items if item['id'] == 'first')
            self.assertTrue(item['favorite'])
            self.assertTrue(item['archived'])

    def test_deleted_and_renamed_paths_are_removed_from_cache(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.make_session(root, 'first')
            second = self.make_session(root, 'second')
            app = self.make_app(root)
            app.history()
            shutil.rmtree(first)
            renamed = root / 'renamed'
            second.rename(renamed)
            items, reads = self.count_json_reads(app)
            self.assertEqual([item['id'] for item in items], ['renamed'])
            self.assertEqual(reads, [renamed / 'session.json'])
            self.assertEqual(set(app._history_cache), {renamed / 'session.json'})

    def test_returned_metadata_cannot_mutate_cache(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root, 'first')
            app = self.make_app(root)
            items = app.history()
            items[0]['name'] = 'caller changed it'
            self.assertEqual(app.history()[0]['name'], 'first')

    def test_invalid_json_does_not_reuse_old_cache_and_recovers(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            sj = self.make_session(root, 'first') / 'session.json'
            valid = sj.read_text()
            app = self.make_app(root)
            app.history()
            sj.write_text('{broken', encoding='utf-8')
            self.assertEqual(app.history(), [])
            self.assertEqual(app._history_cache, {})
            sj.write_text(valid, encoding='utf-8')
            self.assertEqual(app.history()[0]['id'], 'first')

    def test_cache_does_not_retain_full_transcript(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root, 'first', segments=[{'text':'private transcript'}])
            app = self.make_app(root)
            app.history()
            self.assertNotIn('private transcript', repr(app._history_cache))
            self.assertTrue(app._history_cache)

    def test_file_changed_during_read_is_not_cached(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            sj = self.make_session(root, 'first') / 'session.json'
            app = self.make_app(root)
            original = Path.read_text
            def read(path, *args, **kwargs):
                value = original(path, *args, **kwargs)
                if path == sj:
                    meta = json.loads(value)
                    meta['name'] = 'newly written title'
                    path.write_text(json.dumps(meta), encoding='utf-8')
                return value
            with patch.object(Path, 'read_text', read):
                app.history()
            self.assertEqual(app._history_cache, {})
            self.assertEqual(app.history()[0]['name'], 'newly written title')

    def test_transcript_audio_and_group_metadata_refresh_after_write(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            sj = self.make_session(root, 'first', audio='audio.wav') / 'session.json'
            app = self.make_app(root)
            app.history()
            meta = json.loads(sj.read_text())
            meta.update(duration=120, segments=[{'text':'one'}, {'text':'two'}, {'text':''}],
                        notes=[{'text':'note'}], audio=None, group='course',
                        cloud_used=True, stopped=True)
            sj.write_text(json.dumps(meta), encoding='utf-8')
            item = app.history()[0]
            self.assertEqual((item['duration'], item['lines'], item['notes']), (120, 2, 1))
            self.assertEqual((item['hasAudio'], item['group'], item['cloud'], item['stopped']),
                             (False, 'course', True, True))

    def test_removed_json_falls_back_to_legacy_or_orphan(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.make_session(root, 'first')
            second = self.make_session(root, 'second')
            app = self.make_app(root)
            app.history()
            (first / 'session.json').unlink()
            (first / 'transcript.md').write_text('# legacy\n[00:01] words\n', encoding='utf-8')
            (second / 'session.json').unlink()
            (second / 'audio.wav').touch()
            items = {item['id']:item for item in app.history()}
            self.assertTrue(items['first']['legacy'])
            self.assertTrue(items['second']['stopped'])
            self.assertEqual(app._history_cache, {})

    def test_missing_sessions_directory_clears_cache(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / 'sessions'
            root.mkdir()
            self.make_session(root, 'first')
            app = self.make_app(root)
            app.history()
            shutil.rmtree(root)
            self.assertEqual(app.history(), [])
            self.assertEqual(app._history_cache, {})

    def test_parallel_history_requests_return_independent_metadata(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_session(root, 'first')
            app = self.make_app(root)
            app.history()
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(lambda _:app.history(), range(20)))
            self.assertTrue(all(items[0]['name'] == 'first' for items in results))
            results[0][0]['name'] = 'changed by caller'
            self.assertEqual(results[1][0]['name'], 'first')
            self.assertEqual(app.history()[0]['name'], 'first')


if __name__ == "__main__":
    unittest.main()
