import ast
import json
import platform
import re
import threading
import tempfile
import time
import os
import subprocess
import sys
import signal
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)

def load(name, owner=None, **namespace):
    nodes = TREE.body if owner is None else next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == owner).body
    node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    ns = dict(platform=platform, re=re, threading=threading, Path=Path, **namespace)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT / 'app.py'), 'exec'), ns)
    return ns[name]

class WindowsAuditTests(unittest.TestCase):
    @patch.object(platform, 'system', return_value='Windows')
    def test_closing_device_blocks_reopen_until_cleanup_finishes(self, _platform):
        class Recorder:
            stdout=None
            def send_signal(self, sig): pass
            def wait(self, timeout): raise subprocess.TimeoutExpired('WinRec', timeout)
            def kill(self): pass
            def poll(self): return None
        rec=Recorder()
        app=SimpleNamespace(_pending_ff=rec, reader_thread=None, decoder_thread=None,
                            capture_lock=threading.RLock(), raw_f=None)
        load('_kill_ffmpeg_sync', 'App', subprocess=subprocess, signal=signal, WinRec=Recorder)(app)
        self.assertIs(app._winrec_closing,rec)
        constructor=Mock()
        with self.assertRaisesRegex(RuntimeError,'仍在关闭'):
            load('_spawn_winrec', 'App', WinRec=constructor)(app,'mic')
        constructor.assert_not_called()

    def test_whisper_refinish_preserves_summary_speakers_and_rich_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp); source=d/'audio.wav'; source.touch()
            meta={'name':'session','segments':[{'t':0,'text':'old'}], 'summary':'saved summary',
                  'spk_labels':{'S1':'讲者'}, 'notes':[{'t':0,'content':[
                      {'type':'quote','text':'引用'}, {'type':'image','name':'图','file':'note-images/a.png'}]}]}
            (d/'session.json').write_text(json.dumps(meta),encoding='utf-8')
            app=SimpleNamespace(_uncancel=Mock(), _recording_audio_source=lambda *a:source,
                                _whisper_segs=lambda *a,**kw:([{'t':0,'text':'new','spk':'S1'}],{'pretreat':'off'}),
                                _cleanup_recording_audio=Mock(),emit=Mock())
            app._write_md=load('_write_md','App',fmt_ts=lambda t:'00:00').__get__(app)
            app._md_tag=load('_md_tag','App').__get__(app)
            load('_refinish_whisper','App',json=json,Cancelled=type('Cancelled',(Exception,),{}))(app,d,'zh')
            rendered=(d/'transcript.md').read_text(encoding='utf-8')
            for expected in ('saved summary','〔讲者〕new','> 引用','![图](note-images/a.png)'):
                self.assertIn(expected, rendered)

    @unittest.skipUnless(platform.system() == 'Windows', 'native pipe cancellation')
    def test_winrec_timeout_unblocks_a_real_full_pipe(self):
        cls=load('WinRec', os=os, time=time, subprocess=subprocess)
        rec=cls.__new__(cls)
        rec._stop=threading.Event(); rec._shutdown_lock=threading.Lock(); rec._shutdown_done=False
        rec._streams=[]; rec._pa=Mock(); rec.returncode=None
        r,w=os.pipe(); rec.stdout=os.fdopen(r,'rb',buffering=0); rec._w=os.fdopen(w,'wb',buffering=0)
        rec._ew=None; entered=threading.Event(); finished=threading.Event()
        def pump():
            entered.set()
            try: rec._w.write(b'x' * 1024 * 1024)
            except (OSError, ValueError): pass
            finally: rec._shutdown()
        rec._pth=threading.Thread(target=pump, daemon=True); rec._pth.start(); entered.wait(1)
        errors=[]
        def stop():
            try: rec.wait(.01)
            except Exception as e: errors.append(e)
            finally: finished.set()
        worker=threading.Thread(target=stop, daemon=True); worker.start()
        try:
            self.assertTrue(finished.wait(2), 'timeout cleanup blocked on the full pipe')
            rec._pth.join(1)
            self.assertFalse(rec._pth.is_alive())
            self.assertEqual(errors, [])
            rec._pa.terminate.assert_called_once()
        finally:
            # Release a failing implementation without leaving blocked test threads.
            rec.stdout.close()
            worker.join(2); rec._pth.join(2)

    def test_winrec_timeout_does_not_wait_forever_on_driver_shutdown(self):
        cls=load('WinRec', subprocess=subprocess, time=time)
        rec=cls.__new__(cls)
        rec._stop=threading.Event(); rec._shutdown_lock=threading.Lock(); rec._shutdown_done=False
        release=threading.Event(); entered=threading.Event()
        stream=Mock(); stream.stop_stream.side_effect=lambda:(entered.set(),release.wait(5))
        rec._streams=[stream]; rec._pa=Mock(); rec._w=Mock(); rec._ew=None; rec.returncode=None
        rec._pth=threading.Thread(target=rec._shutdown,daemon=True); rec._pth.start(); entered.wait(1)
        finished=threading.Event(); errors=[]
        def wait():
            try: rec.wait(.01)
            except Exception as e: errors.append(e)
            finally: finished.set()
        worker=threading.Thread(target=wait, daemon=True); worker.start()
        try:
            self.assertTrue(finished.wait(2), 'driver shutdown blocked wait')
            self.assertEqual(len(errors),1)
            self.assertIsInstance(errors[0], subprocess.TimeoutExpired)
        finally:
            release.set(); worker.join(2); rec._pth.join(2)

    @unittest.skipUnless(platform.system() == 'Windows', 'requires native Windows process handles')
    def test_native_parent_handle_signals_after_process_exit(self):
        shutdown=threading.Event()
        process=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            watcher=load('make_windows_parent_watcher')(process.pid, shutdown)
            thread=threading.Thread(target=watcher, daemon=True); thread.start()
            self.assertFalse(shutdown.wait(.05))
            process.terminate(); process.wait(timeout=3)
            self.assertTrue(shutdown.wait(2))
            thread.join(2); self.assertFalse(thread.is_alive())
        finally:
            shutdown.set()
            if process.poll() is None: process.kill()
            process.wait(timeout=3)

    def test_audio_url_round_trips_reserved_and_unicode_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); sid='会议 #100%23'; d=root/sid; d.mkdir()
            play='audio #100%.m4a'; (d/play).touch()
            (d/'session.json').write_text(json.dumps({'audio':play}), encoding='utf-8')
            fn=load('load', 'App', SESSIONS_DIR=root, json=json, quote=quote, NOTE_FILE='note.md')
            app=SimpleNamespace(_clean_title=lambda x:x, _read_pref=lambda d:{})
            url=fn(app, sid)['audioUrl']
            self.assertNotIn('#', url)
            self.assertEqual(unquote(url[len('/audio/'):]).split('/'), [sid,play])

    def test_recycle_path_escapes_powershell_quotes(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"a'b.txt"; p.touch(); calls=[]
            def run(cmd, **kw):
                calls.append(cmd); p.unlink(); return SimpleNamespace()
            fn=load('to_trash', subprocess=SimpleNamespace(run=run))
            with patch.object(platform, 'system', return_value='Windows'):
                fn(p)
            self.assertIn("a''b.txt", calls[0][-1])

    def test_homebrew_path_is_mac_only(self):
        blocks=[n for n in TREE.body if isinstance(n, (ast.For, ast.If)) and '/opt/homebrew/bin' in ast.unparse(n)]
        self.assertEqual(len(blocks), 1)
        for system in ('Windows', 'Darwin'):
            env={'PATH':'original'}
            ns=dict(os=SimpleNamespace(environ=env, pathsep=os.pathsep), platform=SimpleNamespace(system=lambda:system))
            exec(compile(ast.Module(body=blocks, type_ignores=[]), 'PATH', 'exec'), ns)
            self.assertEqual(env['PATH']=='original', system=='Windows')

    def test_cancel_after_network_does_not_write_note_or_summary(self):
        Cancelled=type('Cancelled',(Exception,),{})
        for method in ('_study_note_bg', '_cloud_summary_bg'):
            for cancel_at in ([1] if method=='_study_note_bg' else [1,2]):
                with self.subTest(method=method, cancel_at=cancel_at), tempfile.TemporaryDirectory() as temp:
                    d=Path(temp); sj=d/'session.json'; original=json.dumps({'segments':[{'text':'body','t':0}]})
                    sj.write_text(original, encoding='utf-8'); cancelled=set(); calls=[]
                    def ck(sid):
                        def check():
                            if sid in cancelled: raise Cancelled()
                        return check
                    def chat(*a, **kw):
                        calls.append(1)
                        if len(calls)==cancel_at: cancelled.add(d.name)
                        return 'network result'
                    fn=load(method, 'App', json=json, time=time, Cancelled=Cancelled,
                            cloud_chat=chat, MD_RULES='', cloud_think_off_for=lambda *a:False,
                            clean_uploaded_transcript=lambda x:x, outline_transcript=lambda s:('body',{}),
                            parse_summary_outline=lambda *a:('',[{'t':0,'title':'title'}]), NOTE_FILE='note.md',
                            cloud_err_kind=lambda e:'error', cloud_err_text=lambda *a:'error')
                    app=SimpleNamespace(_ck=ck, _cancel=cancelled, stage=Mock(), emit=Mock(), _write_md=Mock())
                    cfg={'provider':'test','model':'test'}
                    if method=='_study_note_bg': fn(app,d,cfg,{'name':'note','prompt':'prompt'},[{'text':'body'}])
                    else: fn(app,d,cfg)
                    self.assertEqual(sj.read_text(encoding='utf-8'), original)
                    self.assertFalse((d/'note.md').exists())
                    app._write_md.assert_not_called()
                    self.assertTrue(app.emit.call_args.kwargs.get('cancelled'))
                    self.assertEqual(len(calls), cancel_at)

    def test_whisper_refinish_uses_shared_markdown_writer(self):
        cls=next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name=='App')
        fn=next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name=='_refinish_whisper')
        self.assertIn('self._write_md(d, meta, self._md_tag(d, meta))', ast.unparse(fn))
        self.assertNotIn("'transcript.md'", ast.unparse(fn))

    def test_parent_watch_holds_handle_and_closes_on_exit_or_shutdown(self):
        factory = load('make_windows_parent_watcher')
        for result in (0, 0xFFFFFFFF, 258):
            shutdown = threading.Event()
            kernel = SimpleNamespace(OpenProcess=Mock(return_value=123), CloseHandle=Mock(), WaitForSingleObject=Mock())
            def wait(handle, millis):
                if result == 258: shutdown.set()
                return result
            kernel.WaitForSingleObject.side_effect=wait
            watcher = factory(42, shutdown, kernel=kernel)
            kernel.OpenProcess.assert_called_once_with(0x00100000, False, 42)
            watcher()
            self.assertTrue(shutdown.is_set())
            kernel.CloseHandle.assert_called_once_with(123)
        kernel.OpenProcess.return_value=0
        shutdown=threading.Event()
        factory(42, shutdown, kernel=kernel)()
        self.assertTrue(shutdown.is_set())

    def test_cloud_chunk_tail_is_not_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); audio=root/'large.m4a'
            with audio.open('wb') as f: f.truncate(21 * 2**20)
            durations=[]
            def run(cmd, **kw):
                durations.append((float(cmd[cmd.index('-ss')+1]), float(cmd[cmd.index('-t')+1])))
                Path(cmd[-1]).touch()
                return SimpleNamespace(returncode=0)
            fn=load('_cloud_asr_openai', probe_dur=lambda p:1900,
                    cache_temp_path=lambda *a:root/'chunk.m4a', ffmpeg_path=lambda:'ffmpeg', SR=16000,
                    subprocess=SimpleNamespace(run=run),
                    _cloud_asr_once=lambda *a:{'segments':[{'start':0, 'end':1, 'text':'中'}], 'text':'中'})
            result=fn({}, audio)
            self.assertEqual(durations, [(0,900), (900,1000)])
            self.assertEqual(result['segments'][1]['start'], 900)

    def test_engine_accepts_float_model_and_survives_corrupt_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'model.onnx').touch()
            factory=Mock(return_value='recognizer')
            engine=load('Engine', sv_model_dir=lambda:root,
                        sherpa_onnx=SimpleNamespace(OfflineRecognizer=SimpleNamespace(from_sense_voice=factory)))
            obj=engine()
            self.assertEqual(factory.call_args.kwargs['model'], str(root/'model.onnx'))
            (root/'model.int8.onnx').touch()
            engine()
            self.assertEqual(factory.call_args.kwargs['model'], str(root/'model.int8.onnx'))
            factory.side_effect=RuntimeError('corrupt model')
            self.assertIsNone(engine()._sv)

    def test_safe_titles_preserve_mac_and_sanitize_windows(self):
        fn = load('safe_title')
        with patch.object(platform, 'system', return_value='Windows'):
            for raw, expected in [('a\\b/c:d*e?f"g<h>i|j\x00', 'a-b-c-d-e-f-g-h-i-j-'),
                                  ('CON.txt', '_CON.txt'), ('lpt9', '_lpt9'),
                                  ('会议. ', '会议'), ('... ', ''), ('中文 😀', '中文 😀')]:
                self.assertEqual(fn(raw), expected)
        with patch.object(platform, 'system', return_value='Darwin'):
            self.assertEqual(fn('a?b/c:d.'), 'a?b-c-d.')

    def make_live_app(self, root, restart_error=False):
        directory = root / 'old-20261029-120000'
        directory.mkdir()
        ns = dict(SESSIONS_DIR=root, ENGINE=SimpleNamespace(new_vad=lambda: None), safe_title=load('safe_title'))
        app = SimpleNamespace(session={'name':'old', 'dir':directory, 'stamp':'20261029-120000', 'mode':'system'},
                              state='recording', gen=1, total_samples=480000, lock=threading.RLock(), decode_lock=threading.RLock(),
                              _stop_ffmpeg_noblock=Mock(), _kill_ffmpeg_sync=Mock(), _drain_vad=Mock(),
                              _start_recorder=Mock(side_effect=RuntimeError('device busy') if restart_error else None),
                              emit=Mock(), status=lambda: {})
        return app, load('rename', 'App', **ns)

    @patch.object(platform, 'system', return_value='Windows')
    def test_rename_collision_does_not_stop_capture(self, _platform):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); app, rename=self.make_live_app(root)
            (root / 'new-20261029-120000').mkdir()
            with self.assertRaisesRegex(RuntimeError, '同名'):
                rename(app, 'new')
            app._stop_ffmpeg_noblock.assert_not_called()

    @patch.object(platform, 'system', return_value='Windows')
    def test_failed_rename_recovers_capture_or_pauses(self, _platform):
        for restart_error in (False, True):
            with self.subTest(restart_error=restart_error), tempfile.TemporaryDirectory() as temp:
                app, rename=self.make_live_app(Path(temp), restart_error)
                with patch('os.rename', side_effect=PermissionError('busy')):
                    with self.assertRaises((RuntimeError, OSError)):
                        rename(app, 'new')
                app._start_recorder.assert_called_once_with('system')
                self.assertEqual(app.state, 'paused' if restart_error else 'recording')
                self.assertEqual(app.session['name'], 'old')
                app.emit.assert_called()

    def test_winrec_wait_timeout_releases_devices_once(self):
        cls=load('WinRec')
        rec=cls.__new__(cls)
        rec._stop=threading.Event(); rec._shutdown_lock=threading.Lock(); rec._shutdown_done=False
        rec._pth=Mock(); rec._pth.is_alive.return_value=True
        stream=Mock(); rec._streams=[stream]; rec._pa=Mock(); rec._w=Mock(); rec._ew=Mock(); rec.returncode=None
        rec.wait(timeout=0)
        rec._shutdown()
        rec._pth.join.assert_called_once_with(0)
        stream.close.assert_called_once()
        rec._pa.terminate.assert_called_once()
        self.assertEqual(rec.returncode, 0)

    def test_volume_rejected_before_coreaudio_access(self):
        target = Mock(side_effect=AssertionError('CoreAudio called'))
        fn = load('volume_set', volume_target=target)
        with patch.object(platform, 'system', return_value='Windows'):
            with self.assertRaisesRegex(RuntimeError, '当前平台不支持'):
                fn(50)
        target.assert_not_called()

    def test_staging_creates_embedded_page_and_preview_assets(self):
        stage = (ROOT / 'tauri-shell/stage_windows.js').read_text(encoding='utf-8')
        self.assertIn("'dist'", stage)
        self.assertIn('background:transparent', stage)
        self.assertIn('material-preview-lakeside.png', stage)
        config = json.loads((ROOT / 'tauri-shell/tauri.windows.conf.json').read_text())
        self.assertIn('program-windows/assets/', config['bundle']['resources'])

    def test_shell_rejects_embedded_http_page(self):
        source = (ROOT / 'tauri-shell/src/main.rs').read_text(encoding='utf-8')
        self.assertIn('is_backend_page(payload.url())', source)
        self.assertIn('fn backend_page_excludes_tauri_localhost()', source)
        self.assertIn('#[cfg(target_os = "macos")]\nuse tauri::menu', source)

    def test_dependency_probe_requires_all_runtime_imports(self):
        source=(ROOT/'tauri-shell/src/main.rs').read_text(encoding='utf-8')
        probe=source[source.index('fn has_tingdao_deps('):source.index('fn pick_ready(')]
        self.assertIn('.all(', probe)
        for name in ('numpy', 'sherpa_onnx', 'pyaudiowpatch'):
            self.assertIn(name, source)

if __name__ == '__main__':
    unittest.main()
