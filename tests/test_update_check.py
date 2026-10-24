import ast
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest


def load_update_functions(system, app_version="3.1.0", releases=None):
    tree = ast.parse(Path('app.py').read_text(encoding='utf-8'))
    names = {'UPDATE_RELEASES_API', 'UPDATE_CACHE_SECONDS', '_update_cache', '_update_lock',
             'UPDATE_PLATFORMS', 'version_tuple', 'platform_release', 'platform_notes', 'check_update'}
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name in names)
             or (isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in names for t in n.targets))]
    ns = {'re': re, 'time': time, 'threading': threading, 'APP_VERSION': app_version,
          'platform': SimpleNamespace(system=lambda: system)}
    exec(compile(ast.Module(nodes, []), 'app.py', 'exec'), ns)
    return ns


RELEASES = [
    {"tag_name": "v3.1.0", "html_url": "https://github.com/Ayin-git1/tingdao/releases/tag/v3.1.0",
     "body": "- 共用改进\n安装包：macOS Apple Silicon（arm64）。\n- Windows 托盘修复",
     "assets": [
         {"name": "SHA256SUMS.txt", "updated_at": "2026-10-07"},
         {"name": "tingdao_3.1.0_aarch64.dmg", "updated_at": "2026-10-07", "browser_download_url": "old.dmg"},
         {"name": "tingdao_3.1.0_20261012_aarch64.dmg", "updated_at": "2026-10-12", "browser_download_url": "new.dmg"},
     ]},
    {"tag_name": "v3.0.0-beta", "prerelease": True,
     "assets": [{"name": "beta_win_x64-setup.exe", "updated_at": "2026-10-01"}]},
    {"tag_name": "v2.7.10", "body": "", "assets": [
        {"name": "tingdao_2.7.10_win_x64-setup.exe", "updated_at": "2026-09-28", "browser_download_url": "win.exe"}]},
]


class UpdateCheckTests(unittest.TestCase):
    def test_version_tuple_orders_numerically(self):
        vt = load_update_functions('Darwin')['version_tuple']
        self.assertGreater(vt('v3.10.0'), vt('3.9.9'))
        self.assertEqual(vt('v3.1.0'), (3, 1, 0))
        self.assertEqual(vt(''), ())

    def test_each_platform_finds_its_own_latest_installer(self):
        mac = load_update_functions('Darwin')
        rel, asset = mac['platform_release'](RELEASES, 'Darwin')
        self.assertEqual((rel['tag_name'], asset['browser_download_url']), ('v3.1.0', 'new.dmg'))
        win = load_update_functions('Windows')
        rel, asset = win['platform_release'](RELEASES, 'Windows')
        # 跳过预发布, 也不把只有 dmg 的 v3.1.0 当成 Windows 新版
        self.assertEqual((rel['tag_name'], asset['browser_download_url']), ('v2.7.10', 'win.exe'))

    def test_notes_drop_lines_only_about_the_other_platform(self):
        ns = load_update_functions('Windows')
        notes = ns['platform_notes'](RELEASES[0]['body'], 'Windows')
        self.assertIn('Windows 托盘修复', notes)
        self.assertNotIn('macOS Apple Silicon', notes)
        self.assertIn('共用改进', notes)


if __name__ == '__main__':
    unittest.main()
