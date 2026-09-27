import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "app.py"
MAIN_RS = ROOT / "tauri-shell/src/main.rs"
WINDOWS_TAURI = ROOT / "tauri-shell/tauri.windows.conf.json"
WINDOWS_STAGE = ROOT / "tauri-shell/stage_windows.js"


class WindowsAdaptationTests(unittest.TestCase):
    def test_status_includes_runtime_platform(self):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "App")
        status = next(node for node in app.body
                      if isinstance(node, ast.FunctionDef) and node.name == "status")
        result = next(node for node in ast.walk(status) if isinstance(node, ast.Return))
        fields = {key.value: value for key, value in zip(result.value.keys, result.value.values)
                  if isinstance(key, ast.Constant)}
        self.assertEqual(ast.unparse(fields.get("platform")), "platform.system()")

    def test_served_index_html_is_stamped_with_platform(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn('"__TINGDAO_PLATFORM__", platform.system()', source,
                      "do_GET must inject platform so Windows never paints a ⌘ first frame")

    def test_headless_shutdown_endpoint_is_available(self):
        source = APP.read_text(encoding="utf-8")
        self.assertTrue('u.path == "/api/shutdown"' in source, "headless shutdown route must exist")
        self.assertTrue("SHUTDOWN_REQUEST.set()" in source, "shutdown route must signal the main loop")
        self.assertIn("APP.stop()", source, "backend shutdown must finish an active recording")
        self.assertIn('while APP.state != "idle"', source, "backend must wait for the save to finish")

        shell = MAIN_RS.read_text(encoding="utf-8")
        self.assertIn("POST /api/shutdown", shell, "Tauri must request graceful backend shutdown")
        self.assertIn("SHUTDOWN_TIMEOUT_SECS", shell, "shell must bound graceful shutdown")
        self.assertIn("c.kill()", shell, "shell must force-stop only after the timeout")

    def test_windows_native_file_picker_and_explorer_reveal_are_used(self):
        source = APP.read_text(encoding="utf-8")
        self.assertTrue('platform.system() == "Windows"' in source, "Windows branches must exist")
        self.assertTrue("System.Windows.Forms.OpenFileDialog" in source, "Windows import dialog must be native")
        self.assertTrue('"explorer.exe"' in source, "Windows project reveal must use Explorer")
        self.assertIn('"\\\\" in sid', source, "session path guards must reject Windows separators")

    def test_windows_bundle_has_nsis_and_only_windows_program_resources(self):
        self.assertTrue(WINDOWS_TAURI.is_file())
        config = WINDOWS_TAURI.read_text(encoding="utf-8")
        self.assertTrue('"nsis"' in config, "Windows build must target NSIS")
        self.assertTrue('"program-windows/app.py"' in config, "Windows bundle must include the Python app")
        self.assertNotIn("TingdaoMic.app", config)
        self.assertNotIn("tingdao-mix", config)

    def test_windows_staging_copies_only_cross_platform_runtime_files(self):
        source = WINDOWS_STAGE.read_text(encoding="utf-8")
        self.assertIn("'app.py', 'index.html', 'whisper_worker.py'", source)
        self.assertIn("'program-windows'", source)
        self.assertNotIn("tingdao-mix", source)

    def test_windows_shell_uses_tauri_resource_directory_and_native_chrome(self):
        source = MAIN_RS.read_text(encoding="utf-8")
        self.assertTrue("app.path().resource_dir()" in source, "shell must use Tauri's resource directory")
        self.assertTrue('"program-windows"' in source, "Windows resource folder must be selected")
        self.assertTrue("Scripts" in source, "Windows venv path must use Scripts")
        self.assertTrue("MessageBoxW" in source, "Windows startup errors must be visible")


if __name__ == "__main__":
    unittest.main()
