import ast
import json
import os
import platform
import shutil
import subprocess
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
APP = ROOT / "app.py"
WINDOWS_STAGE = ROOT / "tauri-shell/stage_windows.js"
WINDOWS_TAURI = ROOT / "tauri-shell/tauri.windows.conf.json"


class CloudFfmpegTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(APP.read_text(encoding="utf-8"))
        cls.app_class = next(node for node in cls.tree.body
                             if isinstance(node, ast.ClassDef) and node.name == "App")
        cls.methods = {node.name: node for node in cls.app_class.body
                       if isinstance(node, ast.FunctionDef)}
        cls.functions = {node.name: node for node in cls.tree.body
                         if isinstance(node, ast.FunctionDef)}

    def make_failure_harness(self, root, failure):
        names = ("_cloud_asr_bg", "_cloud_asr_then_post", "_worker_loop",
                 "_enqueue", "_job_begin", "_job_end", "emit")
        namespace = {
            "Cancelled": type("Cancelled", (Exception,), {}),
            "SESSIONS_DIR": root,
            "json": json,
            "time": __import__("time"),
            "threading": threading,
            "os": os,
            "platform": platform,
            "print": lambda *args, **kwargs: None,
        }
        helpers = ast.Module(body=[self.functions["cloud_err_kind"],
                                   self.functions["cloud_err_text"]], type_ignores=[])
        exec(compile(ast.fix_missing_locations(helpers), str(APP), "exec"), namespace)
        module = ast.Module(body=[self.methods[name] for name in names], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), namespace)
        Harness = type("Harness", (), namespace)
        app = Harness()
        app.lock = threading.RLock()
        app._cond = threading.Condition(app.lock)
        app._q_cloud, app._q_local = [], []
        app._tls = threading.local()
        app.progs = {}
        app.events = []
        app.seq = 0
        app.refining = None
        app.refining_kind = None
        app._mark_stopped = lambda d: None
        app._cloud_recording_source = lambda d, meta: failure()
        return app

    def test_asr_post_worker_broadcasts_failure_when_emit_end_is_false(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session = root / "s1"
            session.mkdir()
            (session / "session.json").write_text(
                json.dumps({"duration": 10, "segments": []}), encoding="utf-8")
            app = self.make_failure_harness(
                root, lambda: (_ for _ in ()).throw(FileNotFoundError(2, "no ffmpeg")))
            app._job_begin("s1", "cloud", state="wait")
            app._enqueue("s1", "cloud", lambda: app._cloud_asr_bg(
                session, {"base_url": "https://example.test"}, emit_end=False))
            class StopAfterOne(threading.Condition):
                waits = 0

                def wait(self, timeout=None):
                    self.waits += 1
                    if self.waits > 1:
                        raise RuntimeError("worker harness finished")
                    return super().wait(timeout)

            app._cond = StopAfterOne(app.lock)

            def run_worker():
                try:
                    app._worker_loop(True)
                except RuntimeError as exc:
                    if str(exc) != "worker harness finished":
                        raise

            worker = threading.Thread(target=run_worker, daemon=True)
            worker.start()
            worker.join(2)
            events = [event for event in app.events if event.get("type") == "refinish"]
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0].get("ok", True))
            self.assertTrue(events[0].get("err"))
            self.assertEqual(events[0].get("err_kind"), "ffmpeg")

    def test_asr_post_worker_broadcasts_cancel_when_emit_end_is_false(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session = root / "s1"
            session.mkdir()
            (session / "session.json").write_text(
                json.dumps({"duration": 10, "segments": []}), encoding="utf-8")
            app = self.make_failure_harness(root, lambda: None)
            app._cloud_recording_source = lambda d, meta: (_ for _ in ()).throw(
                app.Cancelled("cancelled"))
            app._job_begin("s1", "cloud", state="wait")
            app._enqueue("s1", "cloud", lambda: app._cloud_asr_bg(
                session, {"base_url": "https://example.test"}, emit_end=False))

            class StopAfterOne(threading.Condition):
                waits = 0

                def wait(self, timeout=None):
                    self.waits += 1
                    if self.waits > 1:
                        raise RuntimeError("worker harness finished")
                    return super().wait(timeout)

            app._cond = StopAfterOne(app.lock)

            def run_worker():
                try:
                    app._worker_loop(True)
                except RuntimeError as exc:
                    if str(exc) != "worker harness finished":
                        raise

            worker = threading.Thread(target=run_worker, daemon=True)
            worker.start()
            worker.join(2)
            events = [event for event in app.events if event.get("type") == "refinish"]
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0].get("ok", True))
            self.assertTrue(events[0].get("cancelled"))

    def test_windows_staging_supplies_ffmpeg_executables_to_bundle(self):
        stage = WINDOWS_STAGE.read_text(encoding="utf-8")
        config = WINDOWS_TAURI.read_text(encoding="utf-8")
        self.assertIn("ffmpeg.exe", stage)
        self.assertIn("ffprobe.exe", stage)
        self.assertIn("program-windows/ffmpeg/", config)

    def test_windows_resolver_prefers_bundled_tools_then_path(self):
        method = self.functions["ffmpeg_path"]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            bundled = root / "ffmpeg" / "ffmpeg.exe"
            bundled.parent.mkdir()
            bundled.touch()
            namespace = {"Path": Path, "platform": SimpleNamespace(system=lambda: "Windows"),
                         "shutil": shutil, "__file__": str(root / "app.py")}
            module = ast.Module(body=[method], type_ignores=[])
            exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), namespace)
            with patch.object(shutil, "which", return_value="C:/tools/ffmpeg.exe"):
                self.assertEqual(namespace["ffmpeg_path"](), str(bundled.resolve()))
            bundled.unlink()
            with patch.object(shutil, "which", return_value="C:/tools/ffmpeg.exe"):
                self.assertEqual(namespace["ffmpeg_path"](), "C:/tools/ffmpeg.exe")

    def test_posix_resolver_keeps_using_path(self):
        method = self.functions["ffmpeg_path"]
        namespace = {"Path": Path, "platform": SimpleNamespace(system=lambda: "Darwin"),
                     "shutil": shutil, "__file__": str(APP)}
        module = ast.Module(body=[method], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(APP), "exec"), namespace)
        with patch.object(shutil, "which", return_value="/opt/homebrew/bin/ffmpeg"):
            self.assertEqual(namespace["ffmpeg_path"](), "/opt/homebrew/bin/ffmpeg")

    def test_refine_failure_after_asr_has_one_terminal_event(self):
        asr_source = ast.get_source_segment(
            APP.read_text(encoding="utf-8"), self.methods["_cloud_asr_bg"])
        self.assertEqual(asr_source.count("if emit_end:"), 2)
        with TemporaryDirectory() as temp:
            app = self.make_failure_harness(Path(temp), lambda: None)
            app._cloud_asr_bg = lambda d, cfg, emit_end=True: True
            app._cloud_refine_bg = lambda d, cfg: app.emit(
                type="refinish", id=d.name, kind="cloud", ok=False, err="post failed")
            app._cloud_asr_then_post(Path(temp) / "s1", {})
            terminal = [event for event in app.events if event.get("type") == "refinish"]
            self.assertEqual(len(terminal), 1)
            self.assertFalse(terminal[0]["ok"])

    def test_local_post_and_manual_cloud_button_keep_their_routes(self):
        cloud_transcribe = ast.get_source_segment(
            APP.read_text(encoding="utf-8"), self.methods["cloud_transcribe"])
        stop_bg = ast.get_source_segment(
            APP.read_text(encoding="utf-8"), self.methods["_stop_bg"])
        frontend = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('self._cloud_asr_then_post if cloud_flow() == "asr_post" else self._cloud_asr_bg',
                      cloud_transcribe)
        self.assertIn('mode == "cloud" and cloud_flow() == "local_post"', stop_bg)
        self.assertIn("post_flow=True", stop_bg)
        self.assertIn("clRun('/api/cloud_transcribe'", frontend)

    def test_cloud_preflight_is_before_queue_and_emits_failure_for_ui(self):
        method = self.methods["cloud_transcribe"]
        calls = [node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(method) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))]
        self.assertIn("ffmpeg_path", calls)
        self.assertIn("emit", calls)
        source = ast.get_source_segment(APP.read_text(encoding="utf-8"), method)
        self.assertLess(source.index("ffmpeg_path()"), source.index("self._enqueue("))
        error_text = ast.get_source_segment(APP.read_text(encoding="utf-8"),
                                            self.functions["cloud_err_text"])
        self.assertIn("Windows未安装 ffmpeg", error_text)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            session = root / "s1"
            session.mkdir()
            (session / "session.json").write_text(
                json.dumps({"duration": 10, "segments": []}), encoding="utf-8")
            namespace = {
                "SESSIONS_DIR": root,
                "json": json,
                "cloud_cfg": lambda: {"enable": True},
                "cloud_flow": lambda: "asr_post",
                "ffmpeg_path": lambda: (_ for _ in ()).throw(
                    FileNotFoundError("ffmpeg.exe missing")),
                "cloud_err_text": lambda kind, error: "Windows未安装 ffmpeg，无法准备上传音频。",
            }
            helpers = ast.Module(body=[self.methods["emit"], method], type_ignores=[])
            exec(compile(ast.fix_missing_locations(helpers), str(APP), "exec"), namespace)
            Harness = type("Harness", (), namespace)
            app = Harness()
            app.state, app.progs = "idle", {}
            app.lock, app.seq, app.events = threading.RLock(), 0, []
            app._recording_audio_source = lambda d, meta: d / "audio.wav"
            app._uncancel = lambda sid: self.fail("missing ffmpeg must not start a job")
            app._job_begin = lambda *args, **kwargs: self.fail("missing ffmpeg must not enqueue")
            app._enqueue = lambda *args, **kwargs: self.fail("missing ffmpeg must not enqueue")
            result = app.cloud_transcribe("s1")
            self.assertIn("Windows未安装 ffmpeg", result["error"])
            self.assertEqual(len(app.events), 1)
            self.assertEqual(app.events[0]["type"], "refinish")
            self.assertFalse(app.events[0]["ok"])
            self.assertEqual(app.events[0]["err_kind"], "ffmpeg")


if __name__ == "__main__":
    unittest.main()
