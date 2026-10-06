import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

class ShutdownSignalTests(unittest.TestCase):
    def handler(self, headless=True):
        tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                      and ast.unparse(n.test) == "u.path == '/api/shutdown'")
        method = ast.parse('def shutdown(self):\n pass').body[0]
        method.body = [branch]
        event = threading.Event()
        ns = dict(u=SimpleNamespace(path='/api/shutdown'), HEADLESS=headless, SHUTDOWN_REQUEST=event)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<shutdown>', 'exec'), ns)
        return ns['shutdown'], event

    def test_signal_precedes_response(self):
        shutdown, event = self.handler()
        shutdown(SimpleNamespace(_json=lambda *args: self.assertTrue(event.is_set())))

    def test_disconnected_shell_still_requests_shutdown(self):
        for error in (BrokenPipeError, ConnectionResetError):
            with self.subTest(error=error):
                shutdown, event = self.handler()
                def reply(*args): raise error('shell disconnected')
                shutdown(SimpleNamespace(_json=reply))
                self.assertTrue(event.is_set())

    def test_non_headless_request_does_not_shutdown(self):
        shutdown, event = self.handler(False)
        replies = []
        shutdown(SimpleNamespace(_json=lambda *args: replies.append(args)))
        self.assertFalse(event.is_set()); self.assertEqual(replies[0][1], 404)
