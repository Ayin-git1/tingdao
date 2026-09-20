import unittest
from pathlib import Path


APP = Path(__file__).parents[1] / "app.py"


class MicrophoneModesRouteTests(unittest.TestCase):
    def test_no_web_microphone_mode_bridge(self):
        html = (APP.parent / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("btnMicModes", html)
        self.assertNotIn("/api/microphone_modes", html)

    def test_native_menu_is_the_only_microphone_mode_entry(self):
        shell = (APP.parent / "tauri-shell" / "src" / "main.rs").read_text(encoding="utf-8")
        helper = (APP.parent / "tingdao-mix.swift").read_text(encoding="utf-8")
        self.assertIn("MICROPHONE_MODES_MENU_ID", shell)
        self.assertIn("request_microphone_modes", shell)
        self.assertIn("showSystemUserInterface(.microphoneModes)", helper)

    def test_mic_mode_uses_voice_processing_io(self):
        source = (APP.parent / "tingdao-mix.swift").read_text(encoding="utf-8")
        self.assertIn("kAudioUnitSubType_VoiceProcessingIO", source)
        self.assertIn("AudioUnitRender(unit", source)
        self.assertIn("AVCaptureDevice.activeMicrophoneMode", source)


if __name__ == "__main__":
    unittest.main()
