import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "app.py"
HTML = ROOT / "index.html"


class RecordingModePersistenceTests(unittest.TestCase):
    def test_backend_exposes_a_valid_persisted_record_mode(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("def recording_mode()", source)
        self.assertIn('s["record_mode"] = recording_mode()', source)
        self.assertIn('kk == "record_mode"', source)

    def test_frontend_saves_and_restores_record_mode(self):
        source = HTML.read_text(encoding="utf-8")
        self.assertIn("st.record_mode", source)
        self.assertIn("key:'record_mode'", source)
        self.assertIn("syncRecordModeUI", source)


if __name__ == "__main__":
    unittest.main()
