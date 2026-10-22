import ast
import threading
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

    def test_finish_ignores_partial_master_after_switch_and_failed_restart_keeps_recording(self):
        source = APP.read_text()
        self.assertIn('if (not s.get("modeSwitches") and master_rate >= 8000', source)
        self.assertEqual(source.count('if not self.total_samples:\n                self._discard_fresh_session'), 2)
        self.assertNotIn('for p in (fifo, pidf, logf, ratef, master):', source)


if __name__ == '__main__':
    unittest.main()
