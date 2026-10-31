import ast
import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import tempfile
import time
import threading
import unittest
import unicodedata
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch


def bundle_code():
    tree = ast.parse(Path('app.py').read_text())
    wanted = {'_export_safe_name', 'safe_title', 'valid_username', 'build_export_zip', 'import_note_bundle',
              'unique_session_name'}
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and (n.name in wanted or n.name.startswith('_bundle_'))) or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
               t.id.startswith(('NOTE_BUNDLE_', 'NOTE_SHARE_')) for t in n.targets))]
    ns = dict(Path=Path, hashlib=hashlib, json=json, math=math, os=os, platform=platform,
              re=re, shutil=shutil, stat=stat, tempfile=tempfile, time=time, threading=threading,
              unicodedata=unicodedata, uuid=uuid, zipfile=zipfile,
              NOTE_FILE='note.md', NOTE_IMAGE_DIR='note-images', PREF_FILE='.pref.json',
              NOTE_IMAGE_MIMES={'.png': 'image/png', '.jpg': 'image/jpeg'})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), ns)
    return ns


def make_note(root, sid='original', name='课程'):
    d = root / sid
    d.mkdir(parents=True)
    meta = dict(name=name, duration=12, segments=[dict(t=1, d=2, text='内容', formats=[])],
                notes=[dict(t=2, text='笔记', content=[dict(type='image', file='note-images/a.png',
                     layout='aside', displayWidth=86)])], summary='摘要',
                outline=[dict(t=1, title='章节', level=1)], spk_labels={'S01': '老师'},
                audio='audio.m4a', audioMaster='audio.wav', audioListen=None,
                group='学习', favorite=True, archived=False, lang='zh')
    (d / 'session.json').write_text(json.dumps(meta, ensure_ascii=False))
    (d / 'transcript.md').write_text('# 课程\n[00:01] 内容\n')
    (d / 'note.md').write_text('# 课程\n课后笔记')
    (d / '.pref.json').write_text('{"play_rate":"1.5x","last_pos":4}')
    (d / 'audio.wav').write_bytes(b'RIFF recording')
    (d / 'audio.m4a').write_bytes(b'compressed recording')
    (d / 'note-images').mkdir()
    (d / 'note-images/a.png').write_bytes(b'png')
    (d / '.settings.json').write_text('{"api_key":"secret"}')
    (d / 'raw.s16').write_bytes(b'temporary')
    (d / '.pretreat.wav').write_bytes(b'processing cache')
    return d, meta


class NoteBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.dest = self.root / 'dest'
        self.dest.mkdir()
        self.ns = bundle_code()
        self.d, self.meta = make_note(self.source)
        self.zip = self.root / 'note.zip'

    def export(self):
        self.ns['build_export_zip']([(self.d, '课程')], self.zip, 'Ayin')

    def rewrite_zip(self, mutate):
        with zipfile.ZipFile(self.zip) as z:
            files = {n: z.read(n) for n in z.namelist()}
        mutate(files)
        with zipfile.ZipFile(self.zip, 'w') as z:
            for n, data in files.items():
                z.writestr(n, data)

    def test_zip_and_folder_roundtrip_preserve_complete_note(self):
        self.export()
        with zipfile.ZipFile(self.zip) as z:
            self.assertIn('免责声明.txt', z.namelist())
            self.assertIn('tingdao-note.json', z.namelist())
            self.assertFalse(any('.settings.json' in n or 'raw.s16' in n or '.pretreat.wav' in n for n in z.namelist()))
            unpacked = self.root / 'unpacked'
            z.extractall(unpacked)
        for path, name in [(self.zip, '课程'), (unpacked, '课程（1）')]:
            result = self.ns['import_note_bundle'](path, self.dest)
            self.assertEqual(result['count'], 1)
            self.assertEqual(result['ids'][0]['name'], name)
            actual = self.dest / result['ids'][0]['id']
            expected = dict(self.meta, name=name, imported_note=True)
            loaded = json.loads((actual / 'session.json').read_text())
            loaded.pop('share_author', None)
            self.assertEqual(loaded, expected)
            for f in ['audio.wav', 'audio.m4a', 'note-images/a.png', '.pref.json']:
                self.assertEqual((actual / f).read_bytes(), (self.d / f).read_bytes())
            self.assertTrue((actual / 'transcript.md').read_text().startswith('# ' + name))

    def test_rejects_missing_disclaimer_tampering_and_unsafe_paths_without_writes(self):
        for mutation in [lambda f: f.pop('免责声明.txt', None),
                         lambda f: f.__setitem__('课程/audio.wav', b'corrupt'),
                         lambda f: f.__setitem__('../outside', b'escape'),
                         lambda f: f.__setitem__('课程/extra.exe', b'bad')]:
            self.export()
            self.rewrite_zip(mutation)
            with self.assertRaises(RuntimeError):
                self.ns['import_note_bundle'](self.zip, self.dest)
            self.assertEqual(list(self.dest.iterdir()), [])

    def test_plain_zip_and_wrong_version_rejected(self):
        self.zip.write_bytes(b'not zip')
        with self.assertRaises(RuntimeError):
            self.ns['import_note_bundle'](self.zip, self.dest)
        self.export()
        def mutate(files):
            manifest = json.loads(files['tingdao-note.json'])
            manifest['version'] = 999
            files['tingdao-note.json'] = json.dumps(manifest).encode()
        self.rewrite_zip(mutate)
        with self.assertRaisesRegex(RuntimeError, '版本'):
            self.ns['import_note_bundle'](self.zip, self.dest)

    def test_missing_referenced_resource_and_symlink_refused_on_export(self):
        (self.d / 'audio.wav').unlink()
        with self.assertRaises(RuntimeError):
            self.export()
        self.assertFalse(self.zip.exists())
        (self.d / 'audio.wav').symlink_to(self.d / 'audio.m4a')
        with self.assertRaises(RuntimeError):
            self.export()

    def test_roundtrip_keeps_independent_study_note_title_and_bytes(self):
        text = '# 快捷键速查\n\n自己的标题不等于项目名\n'
        (self.d / 'note.md').write_text(text)
        self.export()
        result = self.ns['import_note_bundle'](self.zip, self.dest)
        self.assertEqual((self.dest / result['ids'][0]['id'] / 'note.md').read_text(), text)

    def test_text_only_note_after_audio_deletion_clears_stale_audio_refs(self):
        self.meta['audio'] = None
        self.meta['audioListen'] = 'audio-listen.m4a'
        (self.d / 'session.json').write_text(json.dumps(self.meta))
        (self.d / 'audio.wav').unlink()
        (self.d / 'audio.m4a').unlink()
        self.export()
        result = self.ns['import_note_bundle'](self.zip, self.dest)
        meta = json.loads((self.dest / result['ids'][0]['id'] / 'session.json').read_text())
        self.assertIsNone(meta['audioMaster'])
        self.assertIsNone(meta['audioListen'])

    def test_names_check_titles_not_timestamp_and_exclude_self(self):
        make_note(self.dest, 'different-timestamp', '课程')
        make_note(self.dest, 'another', '课程（1）')
        fn = self.ns.get('unique_session_name')
        self.assertTrue(callable(fn), '统一重名处理尚未实现')
        self.assertEqual(fn(self.dest, '课程'), '课程（2）')
        self.assertEqual(fn(self.dest, '课程', self.dest / 'different-timestamp'), '课程')
        self.assertEqual(fn(self.dest, '课程（1）'), '课程（2）')

    def test_share_author_uses_username_without_tracking_chain_or_machine_paths(self):
        self.meta.update(source='/Users/private-person/secret/course.mp4',
                         sources=['C:/Users/private-person/secret.mp4'],
                         _tingdao_share={'exports': [{'exporter':'old'}], 'import_id':'old-tracking-id'})
        (self.d / 'session.json').write_text(json.dumps(self.meta))
        self.export()
        with zipfile.ZipFile(self.zip) as z:
            manifest = json.loads(z.read('tingdao-note.json'))
            self.assertNotIn('watermark', manifest)
            meta = json.loads(z.read('课程/session.json'))
            self.assertNotIn('source', meta)
            self.assertNotIn('sources', meta)
            self.assertNotIn('_tingdao_share', meta)
            self.assertEqual(meta['share_author'], 'Ayin')
            alias = meta['share_author']
            self.assertNotIn('private-person', z.read('课程/session.json').decode())
        result = self.ns['import_note_bundle'](self.zip, self.dest)
        imported = self.dest / result['ids'][0]['id']
        meta = json.loads((imported / 'session.json').read_text())
        self.assertEqual(meta['share_author'], alias)
        self.assertNotIn('_tingdao_share', meta)
        self.ns['build_export_zip']([(imported, '课程')], self.root / 'reshare.zip', 'OtherUser')
        with zipfile.ZipFile(self.root / 'reshare.zip') as z:
            meta = json.loads(z.read('课程/session.json'))
            self.assertEqual(meta['share_author'], 'OtherUser')
            self.assertNotIn('_tingdao_share', meta)

    def test_batch_failure_rolls_back_committed_notes(self):
        second, _ = make_note(self.source, 'second', '另一课')
        self.ns['build_export_zip']([(self.d, '课程'), (second, '另一课')], self.zip, 'Ayin')
        real_rename = os.rename
        calls = []
        def fail_second(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError('disk failure')
            return real_rename(src, dst)
        with patch.object(os, 'rename', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.ns['import_note_bundle'](self.zip, self.dest)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_modified_source_during_export_keeps_existing_output(self):
        self.zip.write_bytes(b'previous successful package')
        copy = self.ns['_bundle_copy']
        changed = False
        def change_while_copying(*args):
            nonlocal changed
            result = copy(*args)
            if not changed:
                changed = True
                (self.d / 'session.json').write_text('{"name":"changed during export"}')
            return result
        self.ns['_bundle_copy'] = change_while_copying
        with self.assertRaisesRegex(RuntimeError, '变化'):
            self.export()
        self.assertEqual(self.zip.read_bytes(), b'previous successful package')

    def test_rejects_resource_traversal_and_invalid_metadata_even_with_updated_hashes(self):
        for key, value in [('audio', '../outside.wav'), ('notes', {}), ('duration', -1)]:
            self.export()
            def mutate(files):
                filename = '课程/session.json'
                meta = json.loads(files[filename])
                meta[key] = value
                payload = json.dumps(meta).encode()
                files[filename] = payload
                manifest = json.loads(files['tingdao-note.json'])
                manifest['files'][filename] = {'size':len(payload), 'sha256':hashlib.sha256(payload).hexdigest()}
                files['tingdao-note.json'] = json.dumps(manifest).encode()
            self.rewrite_zip(mutate)
            with self.assertRaises(RuntimeError):
                self.ns['import_note_bundle'](self.zip, self.dest)
            self.assertEqual(list(self.dest.iterdir()), [])

    def test_import_strips_private_paths_even_from_otherwise_valid_package(self):
        self.export()
        def mutate(files):
            filename = '课程/session.json'
            meta = json.loads(files[filename])
            meta.update(dir='/Users/private-person/library', audioUrl='file:///Users/private-person/audio.wav',
                        id='/Users/private-person/private-id', transcribe_src='/Users/private-person/private.wav')
            payload = json.dumps(meta).encode()
            files[filename] = payload
            manifest = json.loads(files['tingdao-note.json'])
            manifest['files'][filename] = {'size':len(payload), 'sha256':hashlib.sha256(payload).hexdigest()}
            files['tingdao-note.json'] = json.dumps(manifest).encode()
        self.rewrite_zip(mutate)
        result = self.ns['import_note_bundle'](self.zip, self.dest)
        text = (self.dest / result['ids'][0]['id'] / 'session.json').read_text()
        self.assertNotIn('private-person', text)

    def test_legacy_import_without_author_remains_identifiable(self):
        self.export()
        def mutate(files):
            filename = '课程/session.json'
            meta = json.loads(files[filename])
            meta.pop('share_author')
            payload = json.dumps(meta).encode()
            files[filename] = payload
            manifest = json.loads(files['tingdao-note.json'])
            manifest['files'][filename] = {'size':len(payload), 'sha256':hashlib.sha256(payload).hexdigest()}
            files['tingdao-note.json'] = json.dumps(manifest).encode()
        self.rewrite_zip(mutate)
        result = self.ns['import_note_bundle'](self.zip, self.dest)
        meta = json.loads((self.dest / result['ids'][0]['id'] / 'session.json').read_text())
        self.assertTrue(meta.get('imported_note'))
        self.assertNotIn('share_author', meta)

    def test_folder_import_ignores_finder_metadata(self):
        self.export()
        folder = self.root / 'folder'
        with zipfile.ZipFile(self.zip) as z:
            z.extractall(folder)
        (folder / '.DS_Store').write_bytes(b'Finder metadata')
        result = self.ns['import_note_bundle'](folder, self.dest)
        self.assertEqual(result['count'], 1)
        self.assertFalse(any(p.name == '.DS_Store' for p in self.dest.rglob('*')))

    def test_file_count_and_total_size_limits_are_enforced(self):
        self.export()
        self.ns['NOTE_BUNDLE_MAX_BYTES'] = 1
        with self.assertRaises(RuntimeError):
            self.ns['import_note_bundle'](self.zip, self.dest)
        self.assertEqual(list(self.dest.iterdir()), [])


class NoteBundleIntegrationTests(unittest.TestCase):
    def harness(self, root):
        import threading
        ns = bundle_code()
        ns.update(SESSIONS_DIR=root, profile_username=lambda:'Ayin')
        tree = ast.parse(Path('app.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in
                   {'rename', '_rename_on_disk', 'import_note_bundle', 'export_sessions', 'pick_note_bundle'}]
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'app.py', 'exec'), ns)
        obj = type('Harness', (), {n.name: ns[n.name] for n in methods})()
        obj.lock = threading.RLock()
        obj.note_bundle_lock = threading.Lock()
        obj.state, obj.session, obj.progs = 'idle', None, {}
        return obj, ns

    def test_bundle_io_does_not_hold_recording_state_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d, _ = make_note(root)
            app, ns = self.harness(root)
            app.pick_save_path = lambda _: str(root / 'export.zip')
            ns.update(export_bundle_name=lambda _: 'export.zip', load_setting=lambda _: '0' * 16)
            def export(*args):
                self.assertFalse(app.lock._is_owned(), '大录音导出不得阻塞状态轮询')
            def importer(*args, **kwargs):
                self.assertFalse(app.lock._is_owned(), '大录音导入不得阻塞状态轮询')
                return {'ok': True}
            ns['build_export_zip'] = export
            ns['import_note_bundle'] = importer
            app.export_sessions([d.name])
            app.import_note_bundle('any.zip')

    def test_historical_rename_adds_suffix_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_note(root, '课程-20261030-100000', '课程')
            d, _ = make_note(root, '其他-20261031-100000', '其他')
            app, _ = self.harness(root)
            result = app.rename('课程', d.name)
            self.assertEqual(result['name'], '课程（1）')
            self.assertEqual(app.rename(result['name'], result['id'])['name'], '课程（1）')
            self.assertEqual(json.loads((root / result['id'] / 'session.json').read_text())['name'], '课程（1）')

    def test_export_uses_current_username_instead_of_imported_author(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d, meta = make_note(root)
            meta['share_author'] = 'OriginalTeacher'
            (d / 'session.json').write_text(json.dumps(meta))
            app, ns = self.harness(root)
            target = root / 'export.zip'
            app.pick_save_path = lambda _: str(target)
            ns['export_bundle_name'] = lambda _: 'export.zip'
            for username in ['Ayin', 'NewName']:
                ns['profile_username'] = lambda: username
                app.export_sessions([d.name])
                with zipfile.ZipFile(target) as z:
                    exported = json.loads(z.read('课程/session.json'))
                    self.assertEqual(exported['share_author'], username)
            self.assertEqual(json.loads((d / 'session.json').read_text())['share_author'], 'OriginalTeacher')

    def test_rename_rejects_paths_outside_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'library'
            root.mkdir()
            outside, _ = make_note(Path(temp), 'outside', '外部')
            app, _ = self.harness(root)
            for sid in ['../outside', str(outside)]:
                with self.assertRaises(RuntimeError):
                    app.rename('被改名', sid)
            self.assertTrue(outside.exists())


if __name__ == '__main__':
    unittest.main()
