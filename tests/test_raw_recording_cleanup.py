import ast
import unittest
from pathlib import Path


APP = Path(__file__).parents[1] / "app.py"


class RawRecordingCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "App")
        cls.finish = next(node for node in app.body
                          if isinstance(node, ast.FunctionDef) and node.name == "_finish")
        cls.delete_session = next(node for node in app.body
                                  if isinstance(node, ast.FunctionDef)
                                  and node.name == "delete_session")

    def test_finish_always_removes_raw_recording_file(self):
        """A sub-second recording has no audio.m4a, but its raw scratch file must not survive."""
        raw_unlinks = [node for node in ast.walk(self.finish)
                       if isinstance(node, ast.Call)
                       and isinstance(node.func, ast.Attribute)
                       and node.func.attr == "unlink"
                       and isinstance(node.func.value, ast.Name)
                       and node.func.value.id == "raw"]
        self.assertEqual(len(raw_unlinks), 1)
        raw_guard = next(node for node in ast.walk(self.finish)
                         if isinstance(node, ast.If)
                         and "raw.exists" in ast.unparse(node.test))
        self.assertGreater(raw_unlinks[0].lineno, raw_guard.end_lineno)

    def test_finish_prefers_and_removes_native_rate_master_scratch(self):
        """高保真母带用于编码，但和 16k 转写缓存一样必须在收尾删除。"""
        source = APP.read_text(encoding="utf-8")
        finish = ast.unparse(self.finish)
        self.assertIn('MASTER_RAW_FILE = "raw-master.s16"', source)
        self.assertIn("master_raw = d / MASTER_RAW_FILE", finish)
        self.assertIn("master_rate", finish)
        self.assertIn("master_raw.unlink()", finish)

    def test_mic_app_receives_master_path_and_rate_file(self):
        """助手须获知会话母带路径，并把实际 VPIO 采样率回报给编码端。"""
        source = APP.read_text(encoding="utf-8")
        start = source.index("    def _spawn_mic_app(self):")
        end = source.index("    def _start_recorder", start)
        body = source[start:end]
        self.assertIn("--master", body)
        self.assertIn("--master-rate-file", body)
        self.assertIn("self.session[\"master_rate\"]", body)

    def test_offline_asr_audio_stays_on_the_16k_transcription_branch(self):
        """高保真母带只服务回放；audio.m4a 仍从 16k raw.s16 编码。"""
        source = APP.read_text(encoding="utf-8")
        start = source.index("            def _enc(with_chain):")
        end = source.index("            r = _enc", start)
        encoder = source[start:end]
        self.assertIn('"-ar", str(SR)', encoder)
        self.assertIn('"-i", str(raw)', encoder)
        self.assertNotIn('"-i", str(source_raw)', encoder)

    def test_master_rate_handoff_failure_stops_the_helper_and_removes_master(self):
        """采样率回报无效时不能留下占麦克风的 App 助手或母带临时文件。"""
        source = APP.read_text(encoding="utf-8")
        start = source.index("    def _spawn_mic_app(self):")
        end = source.index("    def _start_recorder", start)
        body = source[start:end]
        handoff = body[body.index('        try:\n            rate = int(ratef.read_text'):]
        self.assertIn("ff.send_signal(signal.SIGTERM)", handoff)
        self.assertIn("master.unlink()", handoff)

    def test_audio_only_delete_also_trashes_raw_recording_file(self):
        """Deleting a recording before final encoding must not leave an orphan directory."""
        raw_names = [node.value for node in ast.walk(self.delete_session)
                     if isinstance(node, ast.Constant) and node.value == "raw.s16"]
        # Metadata-backed and legacy projects take separate branches.
        self.assertEqual(raw_names, ["raw.s16", "raw.s16"])
        source = ast.unparse(self.delete_session)
        self.assertIn("MASTER_RAW_FILE", source)

if __name__ == "__main__":
    unittest.main()
