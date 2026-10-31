import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from frontend_patch import FrontendPatches, MAX_HTML, RELEASE_API


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.builtin = self.root / 'index.html'
        self.builtin.write_bytes(b'builtin')
        self.clients = []
        self.responses = {}
        self.calls = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.tmp.cleanup()

    def publish(self, revision=1, action='apply', **changes):
        html = b'<html>patched</html>'
        manifest = dict(schema=1, base_version='3.1.9', revision=revision,
                        action=action, asset=f'index-3.1.9-p{revision}.html',
                        size=len(html), sha256=hashlib.sha256(html).hexdigest())
        manifest.update(changes)
        assets = []
        for name, data in [('tingdao-patch.json', json.dumps(manifest).encode()),
                           ('tingdao-patch.sig', b's' * 64), (manifest['asset'], html)]:
            url = f'https://github.com/Ayin-git1/tingdao/releases/download/frontend-patches/{name}'
            assets.append(dict(name=name, browser_download_url=url, state='uploaded'))
            self.responses[url] = data
        self.responses[RELEASE_API] = json.dumps(dict(tag_name='frontend-patches',
            draft=False, prerelease=True, assets=assets)).encode()

    def client(self, verifier=None):
        def fetch(url, limit):
            self.calls.append(url)
            value = self.responses[url]
            if isinstance(value, Exception):
                raise value
            if len(value) > limit:
                raise ValueError('too large')
            return value
        client = FrontendPatches(self.root / 'data', '3.1.9', self.builtin,
                                 verifier=verifier or (lambda m, s: s == b's' * 64), fetch=fetch)
        self.clients.append(client)
        return client

    def test_download_is_pinned_until_next_launch_and_ready_confirms_boot(self):
        self.publish()
        first = self.client()
        self.assertEqual(first.select(), b'builtin')
        self.assertTrue(first.check())
        self.assertEqual(first.select(), b'builtin')
        first.close()
        second = self.client()
        self.assertEqual(second.select(), b'<html>patched</html>')
        self.assertFalse(second.ready('wrong-token'))
        self.assertTrue(second.ready(second.token))
        second.close()
        self.assertEqual(self.client().select(), b'<html>patched</html>')

    def test_failed_first_boot_falls_back_and_does_not_retry_same_revision(self):
        self.publish()
        first = self.client(); first.select(); first.check(); first.close()
        second = self.client(); self.assertIn(b'patched', second.select()); second.close()
        third = self.client(); self.assertEqual(third.select(), b'builtin')
        self.assertFalse(third.check())
        self.assertEqual(third.select(), b'builtin')
        self.publish(revision=2)
        self.assertTrue(third.check())

    def test_signed_rollback_and_replayed_revision(self):
        self.publish()
        client = self.client(); client.select(); self.assertTrue(client.check())
        self.publish(revision=2, action='builtin')
        self.assertTrue(client.check()); client.close()
        client = self.client(); self.assertEqual(client.select(), b'builtin')
        self.publish(revision=1)
        self.assertFalse(client.check())

    def test_invalid_candidates_preserve_builtin(self):
        for change in [dict(base_version='3.1.8'), dict(revision=0), dict(revision=True),
                       dict(action='execute'), dict(asset='../app.py'), dict(size=MAX_HTML+1),
                       dict(size=1), dict(sha256='0'*64), dict(schema=2)]:
            with self.subTest(change=change):
                self.publish(**change)
                client = self.client(); self.assertEqual(client.select(), b'builtin')
                self.assertFalse(client.check()); client.close()

    def test_signature_and_network_errors_are_silent(self):
        self.publish()
        client = self.client(verifier=lambda m, s: False)
        client.select(); self.assertFalse(client.check()); client.close()
        self.responses[RELEASE_API] = OSError('offline')
        client = self.client(); self.assertEqual(client.select(), b'builtin')
        self.assertFalse(client.check())

    def test_second_instance_cannot_mutate_shared_state(self):
        self.publish()
        first = self.client(); first.select()
        second = self.client(); self.assertEqual(second.select(), b'builtin')
        self.assertFalse(second.check())
        self.assertTrue(first.check())

    def test_tampered_local_html_falls_back(self):
        self.publish()
        first = self.client(); first.select(); first.check(); first.close()
        for file in (self.root/'data').rglob('page.html'):
            file.write_bytes(b'tampered')
        self.assertEqual(self.client().select(), b'builtin')

    def test_late_ack_does_not_confirm_newer_download(self):
        self.publish()
        first = self.client(); first.select(); first.check(); first.close()
        second = self.client(); second.select()
        self.publish(revision=2); second.check()
        second.ready(second.token); second.close()
        third = self.client(); self.assertIn(b'patched', third.select()); third.close()
        self.assertEqual(self.client().select(), b'builtin')
