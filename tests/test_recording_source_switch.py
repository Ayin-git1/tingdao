import ast
import threading
import platform
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).parents[1] / 'app.py'


class RecordingSourceSwitchTests(unittest.TestCase):
    def make_app(self, fail_modes=()):
        tree = ast.parse(APP.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'switch_mode']
        namespace = dict(ENGINE=SimpleNamespace(new_vad=lambda: None), SR=16000,
                         RECORDING_MODES=('system', 'mix', 'mic'))
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), str(APP), 'exec'), namespace)
        app = type('Harness', (), namespace)()
        app.lock = threading.RLock(); app.decode_lock = threading.RLock()
        app.gen = 1; app.state = 'recording'; app.total_samples = 16000 * 30
        app.session = {'mode': 'system', 'lang': 'zh'}
        app.events = []; app.started = []
        app.emit = lambda **event: app.events.append(event); app.status = lambda: {}
        app._stop_ffmpeg_noblock = lambda: None; app._kill_ffmpeg_sync = lambda: None
        app._drain_vad = lambda *args: None
        app.chunk_buf = []; app._chunk_t0 = 0

        def start(mode):
            app.started.append(mode)
            if mode in fail_modes:
                raise RuntimeError('缺少屏幕录制权限')
        app._start_recorder = start
        return app

    def test_recording_switch_restarts_with_new_mode_and_records_marker(self):
        app = self.make_app()
        result = app.switch_mode('mic')
        self.assertEqual(result, {'ok': True, 'mode': 'mic', 't': 30.0})
        self.assertEqual((app.session['mode'], app.state, app.gen, app.started), ('mic', 'recording', 2, ['mic']))
        self.assertEqual(app.session['modeSwitches'], [{'t': 30.0, 'from': 'system', 'mode': 'mic'}])
        self.assertEqual(app._chunk_t0, app.total_samples)
        self.assertIn({'type': 'mode_switch', 't': 30.0, 'mode': 'mic', 'from': 'system'}, app.events)

    def test_segment_timestamp_continues_after_source_switch(self):
        app = self.make_app()
        app.session['segments'] = []
        tree = ast.parse(APP.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_decode_seg')
        ns = app.switch_mode.__func__.__globals__
        ns['ENGINE'].recognize = lambda samples, lang: '测试'
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(APP), 'exec'), ns)
        app._decode_seg = ns['_decode_seg'].__get__(app)
        for elapsed, mode in [(30, 'mic'), (65, 'mix'), (90, 'system')]:
            app.total_samples = elapsed * 16000
            app.switch_mode(mode)
            app._decode_seg(SimpleNamespace(start=16000 * 2, samples=[0] * 16000), app.session, app.gen)
            self.assertEqual(app.session['segments'][-1]['t'], elapsed + 2)

    def test_failed_switch_falls_back_to_previous_mode_without_marker(self):
        app = self.make_app(fail_modes=('mix',))
        with self.assertRaisesRegex(RuntimeError, '仍在用原来源录音'):
            app.switch_mode('mix')
        self.assertEqual((app.session['mode'], app.state, app.started), ('system', 'recording', ['mix', 'system']))
        self.assertNotIn('modeSwitches', app.session)

    def test_failed_switch_and_failed_fallback_leaves_recording_paused(self):
        app = self.make_app(fail_modes=('mix', 'system'))
        with self.assertRaisesRegex(RuntimeError, '录音已暂停'):
            app.switch_mode('mix')
        self.assertEqual(app.state, 'paused')

    def test_paused_switch_only_changes_mode_for_resume(self):
        app = self.make_app(); app.state = 'paused'
        app.switch_mode('mix')
        self.assertEqual((app.session['mode'], app.state, app.started), ('mix', 'paused', []))

    def test_same_mode_and_idle_and_unknown_mode(self):
        app = self.make_app()
        self.assertEqual(app.switch_mode('system'), {'ok': True, 'mode': 'system'})
        self.assertEqual(app.started, [])
        with self.assertRaises(RuntimeError):
            app.switch_mode('loopback')
        app.state = 'idle'
        with self.assertRaises(RuntimeError):
            app.switch_mode('mic')

    def test_windows_dispatch_appends_raw_and_recovers_device_failures(self):
        tree = ast.parse(APP.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
                   and n.name in ('_start_recorder', '_spawn_winrec')]
        for fail_modes, state in [((), 'recording'), (('mix',), 'recording'), (('mix', 'system'), 'paused')]:
            with self.subTest(fail_modes=fail_modes), TemporaryDirectory() as temp:
                app = self.make_app()
                app.session['dir'] = Path(temp)
                raw = Path(temp) / 'raw.s16'; raw.write_bytes(b'original PCM')
                attempts=[]
                def fake_winrec(mode, mic):
                    attempts.append(mode)
                    if mode in fail_modes:
                        raise RuntimeError('WASAPI device busy')
                    return SimpleNamespace()
                ns = dict(platform=platform, WinRec=fake_winrec, mic_device=lambda: '', threading=SimpleNamespace(Thread=lambda **kw: SimpleNamespace(start=lambda: None)))
                exec(compile(ast.Module(body=methods, type_ignores=[]), str(APP), 'exec'), ns)
                app._spawn_winrec = ns['_spawn_winrec'].__get__(app)
                app._start_recorder = ns['_start_recorder'].__get__(app)
                app._start_pcm_threads = lambda: None
                app._ffmpeg_err_loop = lambda: None
                with patch.object(platform, 'system', return_value='Windows'):
                    if fail_modes:
                        with self.assertRaises(RuntimeError): app.switch_mode('mix')
                    else:
                        app.switch_mode('mix')
                        self.assertEqual(app.session['modeSwitches'], [{'t':30.0, 'from':'system', 'mode':'mix'}])
                self.assertEqual(app.state, state)
                self.assertEqual(attempts, ['mix', 'system'] if fail_modes else ['mix'])
                if app.raw_f is not None:
                    self.assertEqual(app.raw_f.mode, 'ab')
                    app.raw_f.write(b'continued'); app.raw_f.close()
                    self.assertEqual(raw.read_bytes(), b'original PCMcontinued')
                else:
                    self.assertEqual(raw.read_bytes(), b'original PCM')

    def test_finish_ignores_partial_master_after_switch_and_failed_restart_keeps_recording(self):
        source = APP.read_text()
        self.assertIn('if (not s.get("modeSwitches") and master_rate >= 8000', source)
        self.assertEqual(source.count('if not self.total_samples:\n                self._discard_fresh_session'), 2)
        self.assertNotIn('for p in (fifo, pidf, logf, ratef, master):', source)


if __name__ == '__main__':
    unittest.main()
