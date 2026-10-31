"""Real HTTP transport + publisher + compiled native verifier; opt in with executable path."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from frontend_patch import FrontendPatches, RELEASE_API, fetch_bytes

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('TINGDAO_TEST_PATCH_VERIFIER'), 'requires built native verifier')
class NativePatchIntegration(unittest.TestCase):
    def test_signed_http_download_restart_ready_tamper_and_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory/'index.html'; source.write_text('<html>real signed patch</html>')
            private = directory/'private.pem'; public = directory/'public.hex'
            # The compiled verifier uses the repository public key; private key never leaves ignored storage.
            key = ROOT/'releases/patch-signing/private.pem'
            self.assertTrue(key.is_file())
            def build(revision, rollback=False):
                out = directory/str(revision)
                command = ['node', str(ROOT/'tools/frontend-patch.cjs'), 'build', '--key', str(key),
                           '--base-version', '3.1.9', '--revision', str(revision), '--out', str(out)]
                command += ['--rollback'] if rollback else ['--html', str(source)]
                subprocess.run(command, check=True, capture_output=True)
                return out
            assets_dir = build(1)
            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass
                def do_GET(self):
                    if self.path == '/release':
                        assets = [dict(name=p.name, state='uploaded', browser_download_url=
                            'https://github.com/Ayin-git1/tingdao/releases/download/frontend-patches/'+p.name)
                            for p in assets_dir.iterdir()]
                        body = json.dumps(dict(tag_name='frontend-patches', draft=False,
                                               prerelease=True, assets=assets)).encode()
                    else:
                        body = (assets_dir/self.path.lstrip('/')).read_bytes()
                    self.send_response(200); self.end_headers(); self.wfile.write(body)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            def fetch(url, limit):
                route = 'release' if url == RELEASE_API else url.rsplit('/', 1)[1]
                return fetch_bytes(f'http://127.0.0.1:{server.server_port}/{route}', limit)
            builtin = directory/'builtin.html'; builtin.write_bytes(b'builtin')
            env = {'TINGDAO_PATCH_VERIFIER': os.environ['TINGDAO_TEST_PATCH_VERIFIER']}
            clients = []
            def client():
                manager = FrontendPatches(directory/'data', '3.1.9', builtin, fetch=fetch)
                clients.append(manager); return manager
            try:
                with patch.dict(os.environ, env):
                    first=client(); self.assertEqual(first.select(), b'builtin')
                    self.assertTrue(first.check()); self.assertEqual(first.select(), b'builtin'); first.close()
                    second=client(); self.assertIn(b'real signed patch', second.select())
                    self.assertTrue(second.ready(second.token)); second.close()
                    third=client(); self.assertIn(b'real signed patch', third.select())
                    assets_dir=build(2)
                    (assets_dir/'tingdao-patch.sig').write_bytes(b'X'*64)
                    self.assertFalse(third.check())
                    self.assertIn(b'real signed patch', third.select())
                    assets_dir=build(3, rollback=True)
                    self.assertTrue(third.check()); third.close()
                    self.assertEqual(client().select(), b'builtin')
            finally:
                for manager in clients: manager.close()
                server.shutdown(); server.server_close(); thread.join()
