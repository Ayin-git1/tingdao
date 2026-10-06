import ast
import copy
import json
import subprocess
import threading
import time
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

APP = Path(__file__).parents[1] / 'app.py'

class FinishIOTests(unittest.TestCase):
    def make_app(self, root):
        cls = next(n for n in ast.parse(APP.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {'_finish', 'start', 'rename'}]
        ns = dict(copy=copy, json=json, wave=wave, SR=16000, MASTER_RAW_FILE='raw-master.s16',
                  pretreat_chain=lambda: '', ffmpeg_path=lambda: 'ffmpeg',
                  time=time, save_setting=lambda *args: None, MODE_LABELS={}, fmt_ts=lambda t: str(t),
                  ENGINE=SimpleNamespace(engine_name='other', new_vad=lambda: None))
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), str(APP), 'exec'), ns)
        app = type('Harness', (), ns)(); app.decode_lock=threading.RLock(); app.lock=threading.RLock(); app.gen=1; app.state='stopping'
        app.session=dict(dir=root,name='old',started='now',stamp='stamp',mode='mic',lang='zh',
                         segments=[dict(t=0,text='旧会话')],notes=[])
        app.total_samples=32000; app._drain_vad=lambda *args: self.assertFalse(app.lock._is_owned())
        def encode(*args, **kwargs):
            self.assertFalse(app.lock._is_owned(), 'FFmpeg must run outside the state lock')
            (root/'audio.m4a').write_bytes(b'a'*2048)
            return SimpleNamespace(returncode=0,stderr=b'')
        ns['subprocess']=SimpleNamespace(run=encode)
        (root/'raw.s16').write_bytes(b'\0\0'*32000)
        return app

    def test_file_io_and_ffmpeg_outside_lock(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); app=self.make_app(root); writes=[]
            original_write=Path.write_text
            def write(path,*args,**kwargs):
                self.assertFalse(app.lock._is_owned()); writes.append(path.name)
                if path.name == 'session.json':
                    app.session['segments'][0]['text'] = '后续修改'
                return original_write(path,*args,**kwargs)
            with patch.object(Path,'write_text',write):
                self.assertTrue(app._finish(app.session,app.gen))
            meta=json.loads((root/'session.json').read_text())
            self.assertEqual(meta['segments'][0]['text'],'旧会话'); self.assertEqual(meta['duration'],2)
            self.assertEqual(set(writes),{'session.json','transcript.md'})
            self.assertIn('旧会话', (root/'transcript.md').read_text())
            self.assertNotIn('后续修改', (root/'transcript.md').read_text())
            with wave.open(str(root/'audio.wav')) as audio:
                self.assertEqual(audio.getnframes(),32000)
            self.assertFalse((root/'raw.s16').exists())

    def test_slow_save_releases_state_lock_but_blocks_new_recording(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); app=self.make_app(root); entered=threading.Event(); release=threading.Event()
            errors=[]; original_write=Path.write_text
            def write(path,*args,**kwargs):
                if path.name=='session.json':
                    entered.set(); release.wait(3)
                return original_write(path,*args,**kwargs)
            def finish():
                try: app._finish(app.session,app.gen)
                except BaseException as error: errors.append(error)
            with patch.object(Path,'write_text',write):
                worker=threading.Thread(target=finish); worker.start()
                try:
                    self.assertTrue(entered.wait(3))
                    acquired=app.lock.acquire(timeout=.5)
                    self.assertTrue(acquired,'slow disk IO must not block state queries')
                    if acquired: app.lock.release()
                    with self.assertRaisesRegex(RuntimeError,'已有进行中的会话'):
                        app.start('mic','zh','new')
                finally:
                    release.set(); worker.join(3)
            self.assertEqual(errors,[]); self.assertFalse(worker.is_alive())

    def test_slow_encoder_does_not_block_state_lock_or_allow_new_recording(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); app=self.make_app(root); entered=threading.Event(); release=threading.Event()
            errors=[]; ns=type(app)._finish.__globals__
            def encode(*args, **kwargs):
                entered.set(); release.wait(3)
                (root/'audio.m4a').write_bytes(b'a'*2048)
                return SimpleNamespace(returncode=0,stderr=b'')
            ns['subprocess']=SimpleNamespace(run=encode)
            def finish():
                try: app._finish(app.session,app.gen)
                except BaseException as error: errors.append(error)
            worker=threading.Thread(target=finish); worker.start()
            try:
                self.assertTrue(entered.wait(3))
                acquired=app.lock.acquire(timeout=.3)
                self.assertTrue(acquired,'FFmpeg must not hold the state lock')
                if acquired: app.lock.release()
                with self.assertRaisesRegex(RuntimeError,'已有进行中的会话'):
                    app.start('mic','zh','new')
            finally:
                release.set(); worker.join(3)
            self.assertEqual(errors,[]); self.assertFalse(worker.is_alive())

    def test_failed_filter_retries_without_filter_in_same_session(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); app=self.make_app(root); ns=type(app)._finish.__globals__; commands=[]
            ns['pretreat_chain']=lambda: 'fake-filter'
            def encode(cmd, **kwargs):
                self.assertFalse(app.lock._is_owned()); commands.append(cmd)
                if len(commands)==1:
                    return SimpleNamespace(returncode=1,stderr=b'filter failed')
                (root/'audio.m4a').write_bytes(b'a'*2048)
                return SimpleNamespace(returncode=0,stderr=b'')
            ns['subprocess']=SimpleNamespace(run=encode)
            self.assertTrue(app._finish(app.session,app.gen))
            self.assertEqual(len(commands),2); self.assertIn('-af',commands[0]); self.assertNotIn('-af',commands[1])
            self.assertTrue(all(cmd[-1]==str(root/'audio.m4a') for cmd in commands))
            meta=json.loads((root/'session.json').read_text())
            self.assertEqual(meta['audio'],'audio.m4a'); self.assertEqual(meta['audio_pretreat'],'failed')

    def test_encoder_exception_preserves_wav_and_manuscript(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); app=self.make_app(root); ns=type(app)._finish.__globals__
            def encode(*args, **kwargs): raise RuntimeError('encoder unavailable')
            ns['subprocess']=SimpleNamespace(run=encode)
            self.assertTrue(app._finish(app.session,app.gen))
            meta=json.loads((root/'session.json').read_text())
            self.assertEqual(meta['audio'],'audio.wav'); self.assertEqual(meta['audioMaster'],'audio.wav')
            self.assertIn('旧会话',(root/'transcript.md').read_text())

    def test_current_project_rename_is_blocked_until_save_finishes(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); app=self.make_app(root)
            with self.assertRaisesRegex(RuntimeError,'项目正在保存'):
                app.rename('new')
            self.assertTrue(root.exists()); self.assertEqual(app.session['name'],'old')

    def test_stale_generation_does_not_touch_disk(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); app=self.make_app(root); app.gen=2
            app._drain_vad=lambda *args: self.fail('stale finish ran recognition')
            self.assertFalse(app._finish(app.session,1))
            self.assertFalse((root/'session.json').exists()); self.assertTrue((root/'raw.s16').exists())
