import ast
import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WhisperWorkerPipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.worker = self.root / 'worker.py'
        tree = ast.parse((ROOT / 'app.py').read_text())
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = [n for n in app.body if isinstance(n, ast.FunctionDef)
                   and n.name in {'_whisper_proc', 'cancel_job', 'is_cancelled'}]
        nodes = [n for n in tree.body if
                 (isinstance(n, ast.ClassDef) and n.name in {'WhisperStdout', 'Cancelled'})
                 or (isinstance(n, ast.FunctionDef) and n.name == '_ts_secs')
                 or (isinstance(n, ast.Assign) and any(
                     isinstance(t, ast.Name) and t.id in {'_SEG_LINE', '_TS'} for t in n.targets))]
        nodes.append(ast.ClassDef(name='AuditApp', bases=[], keywords=[], body=methods,
                                  decorator_list=[]))
        self.ns = dict(json=json, os=os, platform=platform, re=re, subprocess=subprocess,
                       sys=sys, tempfile=tempfile, threading=threading,
                       whisper_model=lambda: self.root,
                       cache_temp_path=lambda *args: self.root / 'result.json',
                       load_hotwords=lambda: [], WORKER_PY=str(self.worker),
                       WINDOWS_WORKER_PY=str(self.worker))
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                     str(ROOT / 'app.py'), 'exec'), self.ns)
        self.app = self.ns['AuditApp']()
        self.app.lock = threading.RLock()
        self.app._procs = {}
        self.app._cancel = set()
        self.app.progs = {}
        self.progress = []
        self.ready = threading.Event()
        self.app.pct = lambda pct: (self.progress.append(pct), self.ready.set())

    def run_worker(self, source, cancel=False, total=10):
        self.worker.write_text(
            "import json,sys,time\nfrom pathlib import Path\n"
            "out=Path(sys.argv[sys.argv.index('--out')+1])\n" + source)
        result = {}
        def run():
            try:
                result['value'] = self.app._whisper_proc('audio.wav', 'zh', total, False, 'sid')
            except Exception as error:
                result['error'] = error
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            if cancel:
                self.assertTrue(self.ready.wait(3), 'no live progress before cancellation')
                self.assertTrue(thread.is_alive(), 'worker exited before cancellation')
                self.app.cancel_job('sid')
            thread.join(3)
            self.assertFalse(thread.is_alive(), 'worker blocked while draining output')
        finally:
            proc = self.app._procs.get('sid')
            if proc is not None:
                proc.kill()
            thread.join(3)
        self.assertNotIn('sid', self.app._procs)
        self.assertFalse((self.root / 'result.json').exists())
        return result

    def test_large_stderr_does_not_block_success_or_progress(self):
        result = self.run_worker(
            "sys.stderr.write('x'*2_000_000);sys.stderr.flush()\n"
            "print('[00:00.00 --> 00:05.00] hello',flush=True)\n"
            "out.write_text(json.dumps({'segments':[], 'text':'hello'}))\n")
        self.assertEqual(result.get('value'), {'segments': [], 'text': 'hello'})
        self.assertIn(50, self.progress)

    def test_failure_preserves_exit_code_and_error_tail(self):
        result = self.run_worker(
            "sys.stderr.write('x'*2_000_000+'模型加载失败');sys.stderr.flush()\n"
            "sys.exit(7)\n")
        self.assertIsInstance(result.get('error'), RuntimeError)
        self.assertIn('(7)', str(result['error']))
        self.assertIn('模型加载失败', str(result['error']))

    def test_cancellation_keeps_live_progress_and_cancelled_result(self):
        result = self.run_worker(
            "sys.stderr.write('x'*2_000_000);sys.stderr.flush()\n"
            "print('[00:00.00 --> 00:05.00] hello',flush=True)\n"
            "time.sleep(30)\n", cancel=True)
        self.assertIsInstance(result.get('error'), self.ns['Cancelled'])
        self.assertIn(50, self.progress)

    def test_unknown_duration_keeps_stdout_logging(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.run_worker(
                "print('worker diagnostic',flush=True)\n"
                "out.write_text(json.dumps({'segments':[], 'text':'hello'}))\n", total=0)
        self.assertEqual(result.get('value', {}).get('text'), 'hello')
        self.assertIn('worker diagnostic', output.getvalue())
        self.assertEqual(self.progress, [])

    def test_missing_result_still_reports_failure(self):
        result = self.run_worker("pass\n", total=0)
        self.assertIsInstance(result.get('error'), RuntimeError)
        self.assertIn('无结果文件', str(result['error']))


if __name__ == '__main__':
    unittest.main()
