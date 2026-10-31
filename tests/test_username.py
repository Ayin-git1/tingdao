import ast
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path


def profile_code(settings):
    tree = ast.parse(Path('app.py').read_text())
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in
             {'valid_username', 'profile_username', 'save_username'}]
    ns = dict(re=re, load_setting=lambda k: settings.get(k),
              save_setting=lambda k,v:settings.__setitem__(k,v))
    exec(compile(ast.Module(body=funcs,type_ignores=[]),'app.py','exec'),ns)
    return ns


class UsernameTests(unittest.TestCase):
    def test_first_launch_and_existing_users_without_name_require_setup(self):
        for settings in [{}, {'other':'existing settings'}, {'username':'中文'}, {'username':'name123'}]:
            ns=profile_code(settings)
            self.assertTrue(callable(ns.get('profile_username')), '用户名校验尚未实现')
            self.assertEqual(ns['profile_username'](), '')

    def test_only_ascii_letters_and_bounded_length_are_accepted_and_persisted(self):
        settings={'other':'keep'}
        ns=profile_code(settings)
        self.assertTrue(callable(ns.get('save_username')), '用户名保存尚未实现')
        for bad in ['', '中文', 'A yin', 'Ayin1', 'é', 'Ａｙｉｎ', '../name', 'a'*25, None, 123]:
            with self.assertRaises(RuntimeError):
                ns['save_username'](bad)
            self.assertNotIn('username', settings)
        self.assertEqual(ns['save_username']('Ayin'), {'ok':True,'username':'Ayin'})
        self.assertEqual(ns['profile_username'](), 'Ayin')
        ns['save_username']('NewName')
        self.assertEqual(settings, {'other':'keep','username':'NewName'})

    def test_first_letter_is_capitalized_on_save_and_read(self):
        settings={}
        ns=profile_code(settings)
        self.assertEqual(ns['save_username']('ayin'), {'ok':True,'username':'Ayin'})
        self.assertEqual(settings['username'], 'Ayin')
        settings['username']='doris'
        self.assertEqual(ns['profile_username'](), 'Doris')
