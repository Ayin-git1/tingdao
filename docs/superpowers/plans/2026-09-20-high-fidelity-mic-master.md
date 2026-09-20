# High-Fidelity Microphone Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a native-rate microphone master while retaining the existing 16 kHz real-time transcription stream.

**Architecture:** `tingdao-mix` drains VPIO frames from its ring buffer on a writer thread, writes a native-rate scratch master, and separately downsamples to its existing stdout protocol. `app.py` retains the stdout/VAD/transcription contract, encodes the native scratch master only for default WAV playback, and keeps the 16 kHz branch for the ASR M4A.

**Tech Stack:** Swift, AVAudioConverter, Python, ffmpeg, unittest.

**Spec:** `docs/superpowers/specs/2026-09-20-high-fidelity-mic-master-design.md`

## Global Constraints

- Never perform PCM production by 20 ms polling or zero padding in mic mode.
- Preserve the 16 kHz stdout protocol for VAD and streaming transcription.
- Change only the source-backed test helper; do not touch the DMG or installed release App.
- Build the helper for arm64 / macOS 26.0 and ad-hoc sign `TingdaoMic.app`.

## Review Focus

- Short recordings: invalid native scratch files fall back to the existing 16 kHz encode path.
- Helper stop: all real frames queued before SIGINT reach both scratch outputs.
- Native-rate changes: Python reads the helper-provided rate rather than assuming 44.1 kHz.
- Playback: `audioMaster` points at the high-rate WAV, while VAD still sees 16 kHz.
- Cleanup: deleting a recording removes both raw scratch files.

### Task 1: Native-rate helper master

**Files:**
- Modify: `tingdao-mix.swift`
- Test: `tests/test_mic_capture_pipeline.py`

- [x] Add failing static regression tests requiring `--master`, native-rate writes in `startMicWriter`, a VPIO callback without file I/O, and no callback-time buffer allocation.
- [x] Implement the helper master file handle, open it only for mic mode, and write s16le copies on the writer thread before resampling.
- [x] Close the master handle only after VPIO stops and the ring is drained.
- [x] Run `python3 -m unittest tests/test_mic_capture_pipeline.py` and compile with the macOS 26 target.

### Task 2: Python lifecycle and encoding

**Files:**
- Modify: `app.py`
- Test: `tests/test_raw_recording_cleanup.py`

- [x] Add failing tests for forwarding `--master` from `_spawn_mic_app`, native-rate master encoding, and cleanup of `raw-master.s16`.
- [x] Pass a session-local master path to the helper; retain `raw.s16` as the 16 kHz VAD scratch file.
- [x] Prefer the native scratch file for WAV playback in `_finish`, derive its sample rate from helper metadata, and fall back to 16 kHz when invalid or absent.
- [x] Remove both scratch files on finish and audio deletion; run all Python tests and `py_compile`.

### Task 3: Test-helper deployment and runtime proof

**Files:**
- Modify: generated `TingdaoMic.app/Contents/MacOS/TingdaoMic`

- [x] Compile `tingdao-mix.swift` with `-target arm64-apple-macos26.0` and copy it into `TingdaoMic.app`.
- [x] Re-sign and verify `TingdaoMic.app`; use `vtool -show-build` to confirm `minos 26.0`.
- [x] Start the helper as the registered App, assert `vpio ok` plus nonempty 16 kHz output, and inspect the native scratch file with `ffprobe`.
