import ast
import unittest
from pathlib import Path


APP = Path(__file__).parents[1] / "app.py"


class ImportCloudProgressTests(unittest.TestCase):
    """导入走云端转写时界面曾一直停在 0%: 调 cloud_asr 时没传进度回调和时长。"""

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app_class = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "App")
        cls.fn = next(node for node in app_class.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_import_cloud")

    def test_cloud_asr_gets_progress_callback(self):
        calls = [n for n in ast.walk(self.fn)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "cloud_asr"]
        self.assertEqual(len(calls), 1)
        prog = next((k.value for k in calls[0].keywords if k.arg == "prog"), None)
        self.assertIsNotNone(prog, "cloud_asr 没传 prog, 导入进度会停在 0%")
        self.assertEqual(ast.unparse(prog), "self.cloud_prog")

    def test_duration_is_set_for_wait_estimate(self):
        targets = [ast.unparse(t) for n in ast.walk(self.fn)
                   if isinstance(n, ast.Assign) for t in n.targets]
        self.assertIn("cfg['dur']", targets, "没设 cfg['dur'], 等待阶段估不出进度")


class CloudWaitCurveTests(unittest.TestCase):
    """等待云端识别时旧版线性走到 92% 就钉死, 长音频会在 92% 停好几分钟。"""

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        keep = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name in ("cloud_wait_frac", "cloud_poll_gap")]
        ns = {"math": __import__("math")}
        exec(compile(ast.Module(body=keep, type_ignores=[]), "app.py", "exec"), ns)
        cls.frac, cls.gap = staticmethod(ns["cloud_wait_frac"]), staticmethod(ns["cloud_poll_gap"])

    def test_keeps_moving_after_estimate(self):
        est = 100
        seq = [self.frac(t, est) for t in range(0, 401, 20)]
        self.assertEqual(seq, sorted(seq))
        self.assertAlmostEqual(seq[0], 0.24)
        self.assertAlmostEqual(self.frac(est, est), 0.85)
        # 超出预估 1~3 倍时仍在涨, 且始终低于下载结果的 0.94
        self.assertGreater(self.frac(3 * est, est) - self.frac(2 * est, est), 0.01)
        self.assertLessEqual(self.frac(50 * est, est), 0.94)

    def test_polls_fast_at_first(self):
        self.assertEqual(self.gap(0), 1.0)
        self.assertEqual(self.gap(20), 2.0)
        self.assertEqual(self.gap(120), 3.0)


if __name__ == "__main__":
    unittest.main()
