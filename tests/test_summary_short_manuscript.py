import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

class ShortSummaryTests(unittest.TestCase):
    def test_short_nonempty_manuscripts_can_queue_summary_but_empty_cannot(self):
        source=Path(__file__).parents[1]/'app.py'
        cls=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='App')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='cloud_summary')
        with TemporaryDirectory() as temp:
            root=Path(temp);d=root/'s';d.mkdir()
            ns=dict(json=json,cloud_cfg=lambda:{'enable':True},SESSIONS_DIR=root)
            exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),ns)
            calls=[]
            app=SimpleNamespace(state='idle',progs={},_job_begin=lambda *args,**kwargs:calls.append(args),
                                _enqueue=lambda *args:calls.append(args),_cloud_summary_bg=lambda *args:None)
            for count in [1,2]:
                (d/'session.json').write_text(json.dumps({'refinished':'whisper','segments':[{'text':'正文'}]*count}))
                self.assertTrue(ns['cloud_summary'](app,'s')['ok'])
            self.assertEqual(len(calls),4)
            (d/'session.json').write_text(json.dumps({'segments':[]}))
            with self.assertRaises(RuntimeError):ns['cloud_summary'](app,'s')
