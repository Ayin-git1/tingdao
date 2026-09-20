import re
import subprocess
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "TingdaoMic.app" / "Contents" / "MacOS" / "TingdaoMic"
TEST_APP_HELPER = (Path("/Users/ayin/Applications/听道-测试版.app") / "Contents" / "Resources"
                   / "TingdaoMic.app" / "Contents" / "MacOS" / "TingdaoMic")


class MicHelperDeploymentTests(unittest.TestCase):
    def test_bundle_binary_targets_the_supported_macos_baseline(self):
        """The product targets macOS 26, so LaunchServices must see that exact baseline."""
        output = subprocess.run(["vtool", "-show-build", str(HELPER)],
                                check=True, capture_output=True, text=True).stdout
        minimum = re.search(r"minos (\d+)\.(\d+)", output)
        self.assertIsNotNone(minimum)
        self.assertEqual((int(minimum.group(1)), int(minimum.group(2))), (26, 0))

    def test_test_app_embeds_the_current_microphone_helper(self):
        """热测试壳强制使用包内 Mic App，不能只更新源码目录的同名助手。"""
        self.assertTrue(TEST_APP_HELPER.is_file(), "测试版缺少内嵌 TingdaoMic.app")
        self.assertEqual(HELPER.read_bytes(), TEST_APP_HELPER.read_bytes())


if __name__ == "__main__":
    unittest.main()
