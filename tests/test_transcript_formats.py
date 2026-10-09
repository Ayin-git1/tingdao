import ast
import json
import re
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

class TranscriptFormatTests(unittest.TestCase):
    def harness(self, root):
        tree = ast.parse(Path('app.py').read_text())
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = {n.name:n for n in app.body if isinstance(n, ast.FunctionDef)}
        names = ['format_transcript', '_materialize_note_content', '_note_content_text']
        self.assertTrue(all(n in methods for n in names), 'format and quote methods exist')
        ns = dict(SESSIONS_DIR=root, json=json, re=re)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[methods[n] for n in names],type_ignores=[])), 'app.py','exec'),ns)
        obj=type('Harness',(),ns)();obj.lock=threading.RLock();obj.state='idle';obj.progs={}
        return obj
    def test_format_roundtrip_and_stale_text_rejection(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);d=root/'sample';d.mkdir();p=d/'session.json'
            p.write_text(json.dumps({'segments':[{'t':1,'text':'测试😀文字'}],'notes':[{'t':2,'text':'保留'}]}))
            app=self.harness(root)
            patch={'t':1,'text':'测试😀文字','formats':[{'start':2,'end':4,'style':{'bold':True,'background':'#faebdd'}}]}
            app.format_transcript('sample',[patch])
            saved=json.loads(p.read_text());self.assertEqual(saved['segments'][0]['formats'],patch['formats']);self.assertEqual(saved['notes'][0]['text'],'保留')
            patch['text']='旧文稿'
            with self.assertRaises(RuntimeError):app.format_transcript('sample',[patch])
            self.assertEqual(json.loads(p.read_text()),saved)
    def test_quote_is_plain_text_content(self):
        with TemporaryDirectory() as temp:
            app=self.harness(Path(temp))
            nodes,_=app._materialize_note_content(Path(temp),[{'type':'quote','text':'<script>选中文字</script>'},{'type':'text','text':'我的理解'}],[])
            self.assertEqual(nodes[0],{'type':'quote','text':'<script>选中文字</script>'})
            self.assertIn('选中文字',app._note_content_text(nodes))
