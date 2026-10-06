import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

APP=Path(__file__).parents[1]/'app.py'

class InferenceLockTests(unittest.TestCase):
    def make_app(self, recognize):
        cls=next(n for n in ast.parse(APP.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='App')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'_decode_seg','_emit_chunk','_drain_vad','pause'}]
        engine=SimpleNamespace(recognize=recognize,vad=None)
        ns=dict(platform=SimpleNamespace(system=lambda:'Windows'),ENGINE=engine,SR=16000,CHUNK=1.5,np=SimpleNamespace(sqrt=lambda x:x,mean=lambda x:1))
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods,type_ignores=[])),str(APP),'exec'),ns)
        app=type('Harness',(),ns)();app.decode_lock=threading.RLock();app.lock=threading.RLock();app.gen=1
        app.session={'lang':'zh','segments':[]};app._chunk_t0=0;app.events=[];app.emit=lambda **e:app.events.append(e)
        return app,engine

    def test_slow_inference_releases_state_lock_and_commits_current_result(self):
        entered=threading.Event();release=threading.Event()
        def recognize(*args):entered.set();release.wait(3);return '当前字幕'
        app,_=self.make_app(recognize);seg=SimpleNamespace(samples=[1]*16000,start=0);errors=[]
        def run():
            try:app._decode_seg(seg,app.session,1)
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=run);worker.start()
        try:
            self.assertTrue(entered.wait(3));acquired=app.lock.acquire(timeout=.3)
            self.assertTrue(acquired)
            if acquired:app.lock.release()
        finally:release.set();worker.join(3)
        self.assertEqual(errors,[]);self.assertEqual(app.session['segments'][0]['text'],'当前字幕')
        self.assertEqual(app.events[0]['type'],'line')

    def test_late_segment_cannot_write_into_new_session_or_emit_event(self):
        def recognize(*args):app.session={'lang':'en','segments':[]};app.gen+=1;return '旧字幕'
        app,_=self.make_app(recognize);old=app.session
        app._decode_seg(SimpleNamespace(samples=[1]*10,start=0),old,1)
        self.assertEqual(old['segments'],[]);self.assertEqual(app.session['segments'],[]);self.assertEqual(app.events,[])

    def test_chunk_cannot_advance_new_session_timeline(self):
        class Samples:
            def __mul__(self,other):return self
        def recognize(*args):app.session={'lang':'en','segments':[]};app.gen+=1;app._chunk_t0=100;return '旧流式文字'
        app,_=self.make_app(recognize)
        app._emit_chunk(Samples(),app.session,1)
        self.assertEqual(app.events,[]);self.assertEqual(app._chunk_t0,100)

    def test_terminal_drain_uses_fixed_vad_and_does_not_hold_state_lock(self):
        def recognize(*args):self.assertFalse(app.lock._is_owned());return '尾音'
        app,engine=self.make_app(recognize)
        class Vad:
            def __init__(self):self.remaining=True
            def flush(self):pass
            def empty(self):return not self.remaining
            @property
            def front(self):return SimpleNamespace(samples=[1]*16000,start=16000)
            def pop(self):self.remaining=False
        engine.vad=Vad();app._drain_vad(app.session,app.gen)
        self.assertEqual(app.session['segments'][0]['text'],'尾音')

    def test_duplicate_segment_remains_deduplicated(self):
        app,_=self.make_app(lambda *args:'一句');seg=SimpleNamespace(samples=[1]*10,start=0)
        app._decode_seg(seg,app.session,1);app._decode_seg(seg,app.session,1)
        self.assertEqual(len(app.session['segments']),1);self.assertEqual(len(app.events),1)

    def test_late_terminal_drain_does_not_flush_new_session_vad(self):
        app,engine=self.make_app(lambda *args:self.fail('stale drain inferred'))
        old=app.session;app.session={'lang':'en','segments':[]};app.gen=2
        engine.vad=SimpleNamespace(flush=lambda:self.fail('stale drain flushed new VAD'))
        app._drain_vad(old,1)

    def test_pause_waits_for_current_inference_without_blocking_status_lock(self):
        entered=threading.Event();release=threading.Event();paused=threading.Event();errors=[]
        def recognize(*args):entered.set();release.wait(3);return '暂停前文字'
        app,engine=self.make_app(recognize);app.state='recording';app.total_samples=16000
        engine.new_vad=lambda:None;app.status=lambda:{'state':app.state}
        app._stop_ffmpeg_noblock=lambda:None;app._kill_ffmpeg_sync=lambda:None
        def decode():
            try:
                with app.decode_lock:
                    app._decode_seg(SimpleNamespace(samples=[1]*16000,start=0),app.session,1)
            except BaseException as error:errors.append(error)
        def pause():
            try:app.pause();paused.set()
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=decode);worker.start();self.assertTrue(entered.wait(3))
        pauser=threading.Thread(target=pause);pauser.start()
        try:
            acquired=app.lock.acquire(timeout=.3);self.assertTrue(acquired)
            if acquired:app.lock.release()
            self.assertFalse(paused.is_set())
        finally:release.set();worker.join(3);pauser.join(3)
        self.assertEqual(errors,[]);self.assertTrue(paused.is_set());self.assertEqual(app.state,'paused')
        self.assertEqual(app.session['segments'][0]['text'],'暂停前文字');self.assertEqual(app.gen,2)
