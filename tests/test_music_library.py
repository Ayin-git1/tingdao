import ast
import json
import math
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch


def load_music(root):
    tree = ast.parse(Path('app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MusicLibrary')
    ns = dict(Path=Path, threading=threading, json=json, os=os, uuid=uuid, shutil=shutil,
              subprocess=subprocess, math=math, platform=platform, tempfile=tempfile, ffmpeg_path=lambda name='ffmpeg': shutil.which(name))
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'app.py', 'exec'), ns)
    return ns['MusicLibrary'](root)


class MusicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = load_music(self.root / 'data' / 'music')
        self.source = self.root / '歌曲.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=220:duration=3',
                        '-metadata', 'title=月光', '-metadata', 'artist=测试作者', str(self.source)], check=True)

    def test_import_metadata_persistence_order_and_original_untouched(self):
        before = self.source.read_bytes()
        result = self.library.import_files([str(self.source), str(self.source)])
        self.assertEqual(len(result['added']), 2)
        self.assertEqual(result['tracks'][0]['title'], '月光')
        self.assertEqual(result['tracks'][0]['artist'], '测试作者')
        self.assertEqual(self.source.read_bytes(), before)
        ident = result['added'][0]
        self.assertEqual(self.library.media(ident, 'audio').read_bytes(), before)
        order = result['added'][::-1]
        self.library.save({'order': order, 'volume': .18, 'mode': 'random'})
        actual = load_music(self.library.root).list()
        self.assertEqual([t['id'] for t in actual['tracks']], order)
        self.assertEqual(actual['volume'], .18)
        self.assertEqual(actual['mode'], 'random')
        with self.assertRaises(RuntimeError): self.library.media('../secret', 'audio')
        for bad in ({'order': []}, {'volume': -1}, {'volume': float('nan')}, {'mode': 'bad'}):
            with self.assertRaises(RuntimeError): self.library.save(bad)

    def test_cover_extraction_and_non_native_format_playback_copy(self):
        cover = self.root / 'cover.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=64x64', '-frames:v', '1', str(cover)], check=True)
        tagged = self.root / 'cover.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.source), '-i', str(cover), '-map', '0:a', '-map', '1:v', '-c', 'copy', '-id3v2_version', '3', '-disposition:v', 'attached_pic', str(tagged)], check=True)
        result = self.library.import_files([str(tagged)])
        self.assertTrue(result['tracks'][0]['cover'])
        self.assertTrue(self.library.media(result['added'][0], 'cover').read_bytes().startswith(b'\xff\xd8'))
        flac = self.root / 'music.flac'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.source), str(flac)], check=True)
        result = self.library.import_files([str(flac)])
        self.assertTrue(result['tracks'][-1]['file'].endswith('.m4a'))
        self.assertNotIn('original', result['tracks'][-1])
        self.assertEqual(list(self.library.root.glob('*.flac')), [])
        self.assertTrue(flac.is_file())

    @unittest.skipUnless(platform.system() == 'Darwin', 'Finder resource forks are macOS-specific')
    def test_finder_custom_icon_is_imported_when_audio_tags_have_no_art(self):
        icon = Path('AppIcon.icns').read_bytes()
        payload = len(icon).to_bytes(4, 'big') + icon
        data_offset, map_offset = 256, 256 + len(payload)
        header = b''.join(n.to_bytes(4, 'big') for n in (data_offset, map_offset, len(payload), 50))
        resource_map = (header + b'\0' * 8 + (28).to_bytes(2, 'big') + (50).to_bytes(2, 'big')
                        + b'\0\0' + b'icns' + b'\0\0' + (10).to_bytes(2, 'big')
                        + (128).to_bytes(2, 'big') + b'\xff\xff' + b'\0' * 8)
        Path(str(self.source) + '/..namedfork/rsrc').write_bytes(header + b'\0' * 240 + payload + resource_map)
        result = self.library.import_files([str(self.source)])
        self.assertEqual(len(result['added']), 1)
        self.assertIsNotNone(result['tracks'][0]['cover'])
        self.assertTrue(self.library.media(result['added'][0], 'cover').read_bytes().startswith(b'\xff\xd8'))
        self.assertFalse(self.library._finder_cover(self.root / 'missing.mp3', self.root / 'none.jpg'))

    def test_bad_media_and_failed_catalog_write_leave_no_files(self):
        bad = self.root / 'broken.mp3'; bad.write_bytes(b'bad')
        self.assertFalse(self.library.import_files([str(bad)])['ok'])
        self.assertEqual(list(self.library.root.iterdir()), [])
        with patch.object(self.library, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.library.import_files([str(self.source)])
        self.assertEqual(list(self.library.root.iterdir()), [])

    def test_follow_is_document_scoped_and_preserves_other_preferences(self):
        tree = ast.parse(Path('app.py').read_text())
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        methods = [n for n in app.body if isinstance(n, ast.FunctionDef) and n.name in {'session_pref', '_read_pref'}]
        ns = dict(SESSIONS_DIR=self.root, PREF_FILE='.pref.json', json=json, uuid=uuid, os=os)
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'app.py', 'exec'), ns)
        harness = type('Prefs', (), {n.name: ns[n.name] for n in methods})()
        harness.lock = threading.RLock()
        for name in ('a', 'b'): (self.root / name).mkdir()
        harness.session_pref('a', play_rate='1.5x', last_pos=12, music_follow=True)
        self.assertTrue(harness._read_pref(self.root / 'a')['music_follow'])
        self.assertNotIn('music_follow', harness._read_pref(self.root / 'b'))
        harness.session_pref('a', last_pos=20)
        self.assertTrue(harness._read_pref(self.root / 'a')['music_follow'])
        self.assertEqual(harness._read_pref(self.root / 'a')['play_rate'], '1.5x')
        with self.assertRaises(RuntimeError): harness.session_pref('a', music_follow='yes')
