import ast
import io
import json
import queue
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

APP = Path(__file__).parents[1] / 'app.py'

class RecordingGenerationTests(unittest.TestCase):
    def make_app(self, **extra):
        tree = ast.parse(APP.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        names = {'start', 'resume', 'pause', 'stop', '_stop_bg', '_read_loop', '_decode_loop', '_start_pcm_threads'}
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
        engine = SimpleNamespace(engine_name='other', new_vad=lambda: None)
        namespace = dict(threading=threading, queue=queue, ENGINE=engine,
                         platform=SimpleNamespace(system=lambda: 'Windows'), SR=16000,
                         talk_mode=lambda: 'cloud', cloud_flow=lambda: 'upload', json=json)
        namespace.update(extra)
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), str(APP), 'exec'), namespace)
        app = type('Harness', (), namespace)()
        app.decode_lock = threading.RLock(); app.lock = threading.RLock(); app.capture_lock = threading.RLock()
        app.gen = 1; app.state = 'recording'; app.session = {'mode': 'mic', 'lang': 'zh'}
        app.emit = lambda **event: None; app.status = lambda: {}
        app._start_recorder = lambda mode: None
        app._stop_ffmpeg_noblock = lambda: None; app._kill_ffmpeg_sync = lambda: None
        app._drain_vad = lambda *args: None; app.total_samples = 0
        return app

    def test_start_pause_resume_and_stop_finish_advance_generation(self):
        app = self.make_app(); app.state = 'idle'
        app._new_session = lambda *args: {'mode': 'mic', 'lang': 'zh'}
        app.start('mic', 'zh', 'test'); self.assertEqual(app.gen, 2)
        app.pause(); self.assertEqual((app.gen, app.state), (3, 'paused'))
        app.resume(); self.assertEqual((app.gen, app.state), (4, 'recording'))
        with TemporaryDirectory() as temp:
            app.session['dir'] = Path(temp); app._finish = lambda *args: True
            app._stop_bg(app.session, app.gen)
        self.assertEqual((app.gen, app.state), (5, 'idle'))

    def test_late_reader_cannot_write_into_new_recording(self):
        app = self.make_app(); q = queue.Queue(); app.raw_f = io.BytesIO()
        old = SimpleNamespace(stdout=io.BytesIO(b'old PCM'))
        app.ffmpeg = old; app._pending_ff = None; app.gen = 2
        app._read_loop(old, q, 1)
        self.assertEqual(app.raw_f.getvalue(), b''); self.assertEqual(app.total_samples, 0)
        self.assertIsNone(q.get_nowait())

    def test_stopping_reader_preserves_current_tail(self):
        app = self.make_app(); q = queue.Queue(); app.raw_f = io.BytesIO()
        old = SimpleNamespace(stdout=io.BytesIO(b'1234'))
        app.ffmpeg = None; app._pending_ff = old
        app._read_loop(old, q, 1)
        self.assertEqual(app.raw_f.getvalue(), b'1234'); self.assertEqual(app.total_samples, 2)
        self.assertEqual(q.get_nowait(), b'1234'); self.assertIsNone(q.get_nowait())

    def test_queued_decoder_from_old_generation_never_feeds_new_session(self):
        app = self.make_app(); q = queue.Queue(); q.put(b'old'); app.gen = 2
        app._feed = lambda data: self.fail('stale PCM reached recognition')
        app._decode_loop(q, 1)

    def test_current_decoder_feeds_recording_and_stopping_tail(self):
        class Samples:
            def astype(self, kind): return self
            def __truediv__(self, scale): return self
        np = SimpleNamespace(frombuffer=lambda *args, **kwargs: Samples(), int16=int, float32=float)
        app = self.make_app(np=np)
        for state in ('recording', 'stopping'):
            app.state = state; fed = []; app._feed = fed.append
            q = queue.Queue(); q.put(b'current'); q.put(None)
            app._decode_loop(q, app.gen)
            self.assertEqual(len(fed), 1)

    def test_old_stop_cannot_finalize_new_session(self):
        app = self.make_app(); old = dict(app.session); app.gen = 2
        app._finish = lambda *args: self.fail('old stop finalized new recording')
        app._kill_ffmpeg_sync = lambda: self.fail('old stop touched new capture resources')
        app._stop_bg(old, 1)
        self.assertEqual(app.state, 'recording')

    def test_new_recording_after_idle_does_not_redirect_old_cloud_result(self):
        with TemporaryDirectory() as temp:
            root = Path(temp); (root / 'audio.wav').write_bytes(b'audio')
            (root / 'session.json').write_text('{}')
            app = self.make_app(); old = dict(app.session, dir=root, total_samples=32000)
            new = dict(app.session, dir=root / 'new'); app.session = old
            app._finish = lambda *args: True
            app._recording_audio_source = lambda d, meta: d / 'audio.wav'
            events = []
            def emit(**event):
                events.append(event)
                if event['type'] == 'status':
                    app.session = new; app.gen += 1; app.state = 'recording'
            app.emit = emit
            app._stop_bg(old, 1)
            self.assertTrue(old['cloud_pending']); self.assertNotIn('cloud_pending', new)
            self.assertEqual(events[-1]['id'], root.name); self.assertEqual(events[-1]['dur'], 2)
            self.assertIs(app.session, new); self.assertEqual(app.state, 'recording')

if __name__ == '__main__':
    unittest.main()
