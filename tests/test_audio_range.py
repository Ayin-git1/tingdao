import ast
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]


class AudioRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.session = cls.root / 'project'
        cls.session.mkdir()
        cls.data = bytes(range(256)) * 1024 + b'audio tail'
        for name in ('audio.wav', 'audio.m4a'):
            (cls.session / name).write_bytes(cls.data)
        (cls.session / 'empty.wav').touch()
        tree = ast.parse((ROOT / 'app.py').read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        methods = [n for n in handler.body if isinstance(n, ast.FunctionDef)
                   and n.name in {'do_GET', 'log_message'}]
        ns = dict(urlparse=urlparse, unquote=unquote, re=re, os=os,
                  SESSIONS_DIR=cls.root)
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'app.py', 'exec'), ns)
        harness = type('AudioHandler', (BaseHTTPRequestHandler,),
                       {n.name: ns[n.name] for n in methods})
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), harness)
        cls.addClassCleanup(cls.server.server_close)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={'poll_interval': .05}, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_server)

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.thread.join(3)

    def request(self, range_value=None, name='audio.wav', extra_headers=None):
        headers = dict(extra_headers or {})
        if range_value is not None:
            headers['Range'] = range_value
        connection = HTTPConnection(*self.server.server_address, timeout=3)
        try:
            connection.request('GET', '/audio/project/' + name, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_normal_get_keeps_full_content_and_mime(self):
        for name, mime in (('audio.wav', 'audio/wav'), ('audio.m4a', 'audio/mp4')):
            with self.subTest(name=name):
                status, headers, body = self.request(name=name)
                self.assertEqual(status, 200)
                self.assertEqual(body, self.data)
                self.assertEqual(headers['Content-Type'], mime)
                self.assertEqual(int(headers['Content-Length']), len(body))
                self.assertEqual(headers['Accept-Ranges'], 'bytes')
                self.assertNotIn('Content-Range', headers)

    def test_single_ranges_return_exact_bytes_and_headers(self):
        size = len(self.data)
        cases = [('bytes=100-200', 100, 200), ('bytes=0-0', 0, 0),
                 ('bytes=100-', 100, size - 1), ('bytes=-500', size - 500, size - 1),
                 ('bytes=0-999999', 0, size - 1), ('bytes=-999999', 0, size - 1),
                 (f'bytes={size-1}-', size - 1, size - 1)]
        for name in ('audio.wav', 'audio.m4a'):
            for value, start, end in cases:
                with self.subTest(name=name, range=value):
                    status, headers, body = self.request(value, name)
                    self.assertEqual(status, 206)
                    self.assertEqual(headers['Content-Range'], f'bytes {start}-{end}/{size}')
                    self.assertEqual(int(headers['Content-Length']), end - start + 1)
                    self.assertEqual(body, self.data[start:end+1])
                    self.assertEqual(headers['Accept-Ranges'], 'bytes')

    def test_unsatisfiable_range_returns_416_without_body(self):
        for value in (f'bytes={len(self.data)}-', 'bytes=999999-', 'bytes=-0'):
            with self.subTest(range=value):
                status, headers, body = self.request(value)
                self.assertEqual(status, 416)
                self.assertEqual(headers['Content-Range'], f'bytes */{len(self.data)}')
                self.assertEqual(headers['Content-Length'], '0')
                self.assertEqual(body, b'')

    def test_invalid_or_multiple_ranges_fall_back_to_full_response(self):
        for value in ('bytes=200-100', 'bytes=-', 'bytes=abc', 'items=0-1',
                      'bytes=0-1,10-11', 'bytes=' + '9' * 5000 + '-'):
            with self.subTest(range=value[:40]):
                status, headers, body = self.request(value)
                self.assertEqual(status, 200)
                self.assertNotIn('Content-Range', headers)
                self.assertEqual(body, self.data)

    def test_if_range_without_matching_validator_returns_full_content(self):
        status, headers, body = self.request('bytes=0-1', extra_headers={'If-Range': '"old"'})
        self.assertEqual(status, 200)
        self.assertNotIn('Content-Range', headers)
        self.assertEqual(body, self.data)

    def test_empty_file(self):
        status, headers, body = self.request(name='empty.wav')
        self.assertEqual((status, headers['Content-Length'], body), (200, '0', b''))
        status, headers, body = self.request('bytes=0-', name='empty.wav')
        self.assertEqual((status, headers['Content-Range'], body), (416, 'bytes */0', b''))

    def test_missing_or_unsupported_audio_remains_404(self):
        (self.session / 'other.txt').write_text('not audio')
        for name in ('missing.wav', 'other.txt'):
            self.assertEqual(self.request(name=name)[0], 404)

    def test_audio_is_read_in_bounded_chunks(self):
        original_open = Path.open
        reads = []
        class TrackedFile:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                self.stream.__enter__()
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def read(self, size=-1):
                reads.append(size)
                return self.stream.read(size)
        def tracked_open(path, *args, **kwargs):
            return TrackedFile(original_open(path, *args, **kwargs))
        with patch.object(Path, 'open', tracked_open):
            self.assertEqual(self.request()[0], 200)
        self.assertTrue(reads)
        self.assertTrue(all(0 < size <= 64 * 1024 for size in reads), reads)
        reads.clear()
        with patch.object(Path, 'open', tracked_open):
            self.assertEqual(self.request('bytes=100-200')[0], 206)
        self.assertEqual(reads, [101])

    def test_large_file_tail_seek_reads_only_requested_bytes(self):
        size = 512 * 1024 * 1024
        tail = b'large recording tail'
        with (self.session / 'long.wav').open('wb') as audio:
            audio.seek(size - len(tail))
            audio.write(tail)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole-file read')):
            status, headers, body = self.request(f'bytes={size-len(tail)}-', name='long.wav')
        self.assertEqual(status, 206)
        self.assertEqual(headers['Content-Range'], f'bytes {size-len(tail)}-{size-1}/{size}')
        self.assertEqual(int(headers['Content-Length']), len(tail))
        self.assertEqual(body, tail)

    def test_client_disconnect_stops_streaming_and_closes_file(self):
        handler = self.server.RequestHandlerClass.__new__(self.server.RequestHandlerClass)
        handler.path = '/audio/project/audio.wav'
        handler.headers = {}
        handler.send_response = lambda code: None
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        original_open = Path.open
        opened = []
        def tracked_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            opened.append(stream)
            return stream
        class DisconnectedWriter:
            def write(self, chunk):
                raise BrokenPipeError('player cancelled request')
        handler.wfile = DisconnectedWriter()
        with patch.object(Path, 'open', tracked_open):
            handler.do_GET()
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].closed)


if __name__ == '__main__':
    unittest.main()
