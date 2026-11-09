#!/usr/bin/env python3
"""Repeat WKWebView drag benchmarks on the actual frontend with synthetic data."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]


def seed(data, projects, rows, audio):
    (data / ".settings.json").write_text('{"username":"Benchmark","update_auto":false}')
    groups = [f"测试分组 {i:02d}" for i in range(12)]
    (data / ".groups.json").write_text(json.dumps({"order": groups}))
    for i in range(projects):
        directory = data / f"bench-{i}"
        directory.mkdir()
        segments = [{"t": j * 4, "d": 4, "text": f"第 {j+1} 段。"
                     + "长文稿边界拖选性能测试，包含中英文 mixed text 和标点。" * (2 + j % 6)}
                    for j in range(rows if i == 0 else 1)]
        meta = {
            "name": f"测试录音 {i:04d}", "group": groups[i % len(groups)],
            "segments": segments, "started": "2026-01-01 09:00",
            "duration": len(segments) * 4, "stopped": True, "notes": [],
        }
        if audio and i == 0:
            meta["audio"] = "audio.wav"
            with wave.open(str(directory / "audio.wav"), "wb") as recording:
                recording.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                recording.writeframes(bytes(32000))
        (directory / "session.json").write_text(json.dumps(meta, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=str(Path.home() / "tingdao-venv/bin/python"))
    parser.add_argument("--runs", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--projects", type=int, default=800)
    parser.add_argument("--rows", type=int, default=2400)
    parser.add_argument("--audio", action="store_true", help="Include playback controls on the benchmark transcript")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tingdao-edge-bench-") as folder:
        temp = Path(folder)
        data = temp / "data"
        data.mkdir()
        seed(data, args.projects, args.rows, args.audio)
        binary = temp / "bench"
        subprocess.run(["swiftc", str(Path(__file__).with_suffix(".swift")), "-o", str(binary)], check=True)
        port = temp / "port"
        env = dict(os.environ, TINGDAO_DATA=str(data), TINGDAO_PORTFILE=str(port),
                   PYTHONDONTWRITEBYTECODE="1")
        with (temp / "backend.log").open("w+") as log:
            backend = subprocess.Popen([args.python, str(ROOT / "app.py"), "--no-window"],
                                       cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                for _ in range(200):
                    if port.exists() and port.read_text().strip():
                        break
                    if backend.poll() is not None:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Backend startup timed out")
                if not port.exists():
                    log.seek(0)
                    raise RuntimeError(log.read())
                url = f"http://127.0.0.1:{port.read_text().strip()}/"
                for _ in range(args.runs):
                    for direction in ("down", "up"):
                        subprocess.run([str(binary), url, direction], check=True, timeout=20)
            finally:
                if backend.poll() is None:
                    backend.terminate()
                    try:
                        backend.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        backend.kill()
                        backend.wait()


if __name__ == "__main__":
    main()
