"""Signed, next-launch-only frontend patches. Never modifies the App bundle."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid

RELEASE_API = 'https://api.github.com/repos/Ayin-git1/tingdao/releases/tags/frontend-patches'
ASSET_PREFIX = 'https://github.com/Ayin-git1/tingdao/releases/download/frontend-patches/'
MAX_MANIFEST = 64 * 1024
MAX_HTML = 10 * 1024 * 1024
MAX_NOTES = 8000
CHECK_INTERVAL = 6 * 3600


def fetch_bytes(url, limit):
    import requests
    with requests.get(url, timeout=(5, 15), stream=True,
                      headers={'User-Agent': 'tingdao-frontend-patches',
                               'Cache-Control': 'no-cache'}) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError('patch response too large')
        return bytes(data)


def verify_manifest(manifest, signature):
    executable = os.environ.get('TINGDAO_PATCH_VERIFIER')
    if not executable:
        return False
    with tempfile.TemporaryDirectory(prefix='tingdao-verify-') as directory:
        root = Path(directory)
        (root / 'manifest').write_bytes(manifest)
        (root / 'signature').write_bytes(signature)
        result = subprocess.run([executable, '--verify-frontend-patch',
                                 str(root/'manifest'), str(root/'signature')],
                                timeout=10, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        return result.returncode == 0


class FrontendPatches:
    def __init__(self, data_dir, version, builtin, verifier=verify_manifest, fetch=fetch_bytes):
        self.root = Path(data_dir) / '.frontend-patches' / version
        self.version, self.builtin = version, Path(builtin)
        self.verifier, self.fetch = verifier, fetch
        self.token = uuid.uuid4().hex
        self._mutex = threading.RLock()
        self._lock = None
        self._selected = None
        self._selected_revision = 0
        self._boot_revision = 0
        self._pending_notes = (0, '', '')
        self._state = {}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            lock = (self.root / 'lock').open('a+b')
            try:
                if os.name == 'nt':
                    import msvcrt
                    lock.write(b'\0'); lock.flush(); lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock.close()
                return
            self._lock = lock
            path = self.root / 'state.json'
            if path.exists():
                self._state = json.loads(path.read_text('utf-8'))
                if not isinstance(self._state, dict):
                    self._state = {}
        except (OSError, ValueError):
            self._state = {}

    def close(self):
        if self._lock:
            self._lock.close()
            self._lock = None

    def _save(self, state):
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as file:
            temporary = Path(file.name)
            try:
                file.write(json.dumps(state).encode())
                file.flush()
                os.fsync(file.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, self.root/'state.json')
        finally:
            temporary.unlink(missing_ok=True)
        self._state = state

    def _manifest(self, raw, signature):
        if len(raw) > MAX_MANIFEST or len(signature) != 64 or not self.verifier(raw, signature):
            raise ValueError('invalid patch signature')
        manifest = json.loads(raw)
        if (manifest.get('schema') != 1 or manifest.get('base_version') != self.version
                or type(manifest.get('revision')) is not int or manifest['revision'] <= 0
                or manifest.get('action') not in ('apply', 'builtin')):
            raise ValueError('incompatible patch')
        notes = manifest.get('notes', '')
        if not isinstance(notes, str) or len(notes) > MAX_NOTES:
            raise ValueError('invalid patch notes')
        if manifest['action'] == 'apply':
            if (not re.fullmatch(r'index-[A-Za-z0-9.-]+\.html', manifest.get('asset', ''))
                    or type(manifest.get('size')) is not int
                    or not 0 < manifest['size'] <= MAX_HTML
                    or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('sha256', ''))):
                raise ValueError('invalid patch asset')
        return manifest

    def _page(self, manifest, page):
        if (len(page) != manifest['size'] or len(page) > MAX_HTML
                or hashlib.sha256(page).hexdigest() != manifest['sha256']):
            raise ValueError('invalid patch contents')
        page.decode('utf-8')
        return page

    def select(self):
        """Pin bytes for this process; no remote calls in the startup path."""
        with self._mutex:
            if self._selected is not None:
                return self._selected
            self._selected = self.builtin.read_bytes()
            if not self._lock:
                return self._selected
            try:
                revision = self._state.get('revision', 0)
                # 启动时已落盘的序号(无论最终用补丁、内置页面还是已被拒绝), 之后下载的才算「待重启」。
                self._boot_revision = revision if type(revision) is int else 0
                if type(revision) is not int or revision <= 0 or self._state.get('rejected'):
                    return self._selected
                if self._state.get('booting') and not self._state.get('confirmed'):
                    self._save({**self._state, 'rejected': True})
                    return self._selected
                directory = self.root / str(revision)
                manifest = self._manifest((directory/'manifest.json').read_bytes(),
                                          (directory/'signature').read_bytes())
                if manifest['revision'] != revision or manifest['action'] == 'builtin':
                    return self._selected
                page = self._page(manifest, (directory/'page.html').read_bytes())
                self._save({**self._state, 'booting': True})
                self._selected_revision = revision
                self._selected = page
            except Exception:
                # Corrupt state, missing native verifier or bad signature must not block startup.
                pass
            return self._selected

    def ready(self, token):
        with self._mutex:
            if not self._lock or token != self.token or not self._selected_revision:
                return False
            if self._state.get('revision') != self._selected_revision:
                return False  # A late acknowledgement cannot bless a newly downloaded revision.
            try:
                self._save({**self._state, 'confirmed': True})
                return True
            except OSError:
                return False

    def status(self):
        """给页面看的: 本进程用的序号, 以及已下载、重启后才生效的序号与签名标签里的更新说明。"""
        with self._mutex:
            info = {'supported': True, 'base_version': self.version,
                    'running': self._selected_revision, 'pending': 0, 'action': '', 'notes': ''}
            revision = self._state.get('revision', 0)
            if (not self._lock or type(revision) is not int or revision <= self._boot_revision
                    or self._state.get('rejected')):
                return info
            try:
                if self._pending_notes[0] != revision:
                    directory = self.root / str(revision)
                    manifest = self._manifest((directory/'manifest.json').read_bytes(),
                                              (directory/'signature').read_bytes())
                    self._pending_notes = (revision, manifest['action'], manifest.get('notes', ''))
                _, action, notes = self._pending_notes
            except Exception:
                return info
            return {**info, 'pending': revision, 'action': action, 'notes': notes}

    def check_periodically(self, interval=CHECK_INTERVAL):
        """启动时查一次, 之后每隔 interval 再查; 长时间不退出的窗口也能等到新补丁。"""
        while True:
            self.check()
            time.sleep(interval)

    def check(self):
        """Stage a validated candidate. Keep this process's page unchanged."""
        if not self._lock:
            return False
        if self.verifier is verify_manifest and not os.environ.get('TINGDAO_PATCH_VERIFIER'):
            return False
        try:
            release = json.loads(self.fetch(RELEASE_API, 2 * 1024 * 1024))
            if release.get('tag_name') != 'frontend-patches' or release.get('draft'):
                return False
            assets = {}
            for asset in release['assets']:
                name = asset['name']
                if name in assets:
                    raise ValueError('duplicate patch asset')
                url = asset['browser_download_url']
                if asset.get('state') != 'uploaded' or url != ASSET_PREFIX + name:
                    raise ValueError('unexpected patch asset URL')
                assets[name] = url
            raw = self.fetch(assets['tingdao-patch.json'], MAX_MANIFEST)
            signature = self.fetch(assets['tingdao-patch.sig'], 64)
            manifest = self._manifest(raw, signature)
            revision = manifest['revision']
            with self._mutex:
                if revision <= self._state.get('revision', 0):
                    return False
            page = (self._page(manifest, self.fetch(assets[manifest['asset']], MAX_HTML))
                    if manifest['action'] == 'apply' else None)
            with self._mutex:
                if revision <= self._state.get('revision', 0):
                    return False
                with tempfile.TemporaryDirectory(dir=self.root, prefix='download-') as temporary:
                    directory = Path(temporary) / 'revision'
                    directory.mkdir()
                    (directory/'manifest.json').write_bytes(raw)
                    (directory/'signature').write_bytes(signature)
                    if page is not None:
                        (directory/'page.html').write_bytes(page)
                    destination = self.root / str(revision)
                    # An orphan directory can remain after a crash before state commit.
                    if destination.exists():
                        import shutil
                        shutil.rmtree(destination)
                    os.replace(directory, destination)
                    self._save({'revision': revision, 'booting': False, 'confirmed': False})
            return True
        except Exception:
            return False
