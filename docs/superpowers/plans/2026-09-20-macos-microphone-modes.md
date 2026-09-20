# macOS Native Microphone Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Python's recording and transcription pipeline intact while adding reliable macOS Voice Processing capture and a user-accessible official microphone-mode picker.

**Architecture:** `tingdao-mix` owns the Voice Processing I/O graph and continues to emit the existing 16 kHz mono `s16le` stdout protocol. Python starts and controls that helper, performs capability checks, and retains all file, VAD, and transcription behavior. The web UI adds a recording-only action that invokes the existing loopback endpoint.

**Tech Stack:** Python standard-library HTTP server, Swift, AVFoundation/AVFAudio, ScreenCaptureKit, Tauri macOS test shell, Node test runner, Python unittest.

**Spec:** `docs/superpowers/specs/2026-09-20-macos-microphone-modes-design.md`

## Global Constraints

- Do not add a virtual sound card, private API, or custom noise-reduction algorithm.
- Python continues to consume only 16 kHz mono `s16le` PCM on helper stdout.
- Voice Processing uses Apple `AVAudioEngine`/AVFAudio and must gracefully fall back to ordinary microphone capture.
- Voice Processing API minimum is macOS 10.15; microphone-mode UI minimum is macOS 12.
- Standard, Wide Spectrum, and Voice Isolation remain user choices in macOS UI.
- Do not modify unrelated existing workspace changes.

## Review Focus

- Voice Processing exposes a multi-channel input bus: tap the mono mixer output, never input channel zero.
- A device refuses Voice Processing: the helper must log the reason and still reach `ready` with ordinary mic capture.
- macOS 11 and non-macOS callers: microphone-mode endpoint returns a readable unsupported response without signaling a process.
- A recording is system or mix rather than mic: the UI action is absent and the Python endpoint rejects it.
- The signed test-app helper is stale: verify its `--mode mic --voice-processing` launch logs `ready` after copying and signing.

---

### Task 1: Voice Processing capture graph and ordinary-capture fallback

**Files:**
- Modify: `tingdao-mix.swift:116-186`
- Test: `tests/test_microphone_modes.py`

**Interfaces:**
- Consumes: command option `--voice-processing` and existing `startMic(_:voiceProcessing:)`.
- Produces: `startMic` always delivers a mono `AVAudioPCMBuffer` to the converter; stdout protocol remains `s16le` at `gRate`.

- [ ] **Step 1: Write the failing source-level regression test**

```python
def test_voice_processing_taps_the_mono_mixer_output():
    source = Path("tingdao-mix.swift").read_text()
    assert "let captureNode = voiceProcessing ? mixer : inNode" in source
    assert "captureNode.installTap" in source
    assert "mixer.outputVolume = 0" in source
```

- [ ] **Step 2: Run the regression test to verify it fails**

Run: `python3 -m unittest tests/test_microphone_modes.py`

Expected: FAIL because the existing tap is installed directly on `inNode`.

- [ ] **Step 3: Implement the mono capture-node selection**

```swift
let mixer = engine.mainMixerNode
let captureNode: AVAudioNode
if voiceProcessing, #available(macOS 10.15, *) {
    let inputFormat = inNode.outputFormat(forBus: 0)
    engine.connect(inNode, to: mixer, format: inputFormat)
    engine.connect(mixer, to: engine.outputNode, format: inputFormat)
    mixer.outputVolume = 0
    do {
        try inNode.setVoiceProcessingEnabled(true)
        captureNode = mixer
    } catch {
        log("voice processing unavailable: \(error.localizedDescription); fallback to standard microphone")
        captureNode = inNode
    }
} else {
    captureNode = inNode
}
let captureFormat = captureNode.outputFormat(forBus: 0)
captureNode.installTap(onBus: 0, bufferSize: 4096, format: captureFormat) { buffer, _ in
    // Build AVAudioConverter from captureFormat to 16 kHz mono and preserve existing FIFO write.
}
```

Keep `engine.start()` after graph construction. Do not read `inNode.floatChannelData` while Voice Processing is active.

- [ ] **Step 4: Run the test and compile Swift**

Run:

```bash
python3 -m unittest tests/test_microphone_modes.py
swiftc tingdao-mix.swift -o /tmp/tingdao-mix-check -framework ScreenCaptureKit -framework AVFoundation -framework CoreMedia -framework CoreAudio -framework AudioToolbox
```

Expected: tests pass and Swift exits 0.

- [ ] **Step 5: Verify signed-runtime audio startup**

Run:

```bash
test_bundle='/Users/ayin/Applications/听道-测试版.app'
cp -f tingdao-mix "$test_bundle/Contents/MacOS/tingdao-mix"
codesign --force --sign - --identifier local.tingdao.test "$test_bundle/Contents/MacOS/tingdao-mix"
"$test_bundle/Contents/MacOS/tingdao-mix" --mode mic --rate 16000 --voice-processing >/dev/null 2>/tmp/voice-processing.err &
helper_pid=$!
sleep 3
kill -TERM "$helper_pid"
wait "$helper_pid"
cat /tmp/voice-processing.err
```

Expected: output includes `ready`; it must not report an unknown mode or fail to start.

### Task 2: Python capability, launch, and mode-picker contract

**Files:**
- Modify: `app.py:111-139, 2498-2510, 4385-4386`
- Test: `tests/test_microphone_modes.py`

**Interfaces:**
- Consumes: `is_microphone_modes_supported() -> bool`, `open_microphone_modes(mode: str) -> dict`, and a live `APP.ffmpeg` helper process.
- Produces: `POST /api/microphone_modes` returning `{ "ok": true }` only while a macOS 12+ `mic` session is recording; otherwise `{ "ok": false, "error": str }`.

- [ ] **Step 1: Add failing tests for unsupported systems and live-helper routing**

```python
def test_microphone_modes_require_macos_12(self):
    self.assertFalse(self._support_function("Darwin", "11.7.10"))
    self.assertTrue(self._support_function("Darwin", "12.0"))
    self.assertFalse(self._support_function("Windows", "27.0"))

def test_route_only_delegates_for_microphone_recording(self):
    open_modes, signals = self._function()
    self.assertFalse(open_modes("mix")["ok"])
    self.assertEqual(signals, [])
    self.assertTrue(open_modes("mic")["ok"])
    self.assertEqual(signals, [30])
```

- [ ] **Step 2: Run tests to verify the missing or incorrect behavior**

Run: `python3 -m unittest tests/test_microphone_modes.py`

Expected: FAIL before the capability gate and live-helper signal behavior are implemented.

- [ ] **Step 3: Implement the stable Python bridge**

```python
def is_microphone_modes_supported():
    if platform.system() != "Darwin":
        return False
    try:
        major, minor = (int(part) for part in platform.mac_ver()[0].split(".")[:2])
        return (major, minor) >= (12, 0)
    except (TypeError, ValueError):
        return False

def open_microphone_modes(mode):
    if mode != "mic" or APP.state != "recording" or not APP.session or APP.session.get("mode") != "mic":
        return {"ok": False, "error": "请在“仅麦克风”录制中调整麦克风模式"}
    if not is_microphone_modes_supported():
        return {"ok": False, "error": "麦克风模式需要 macOS 12 或更高版本"}
    try:
        APP.ffmpeg.send_signal(signal.SIGUSR1)
    except OSError as error:
        return {"ok": False, "error": f"无法打开麦克风模式：{error}"}
    return {"ok": True}
```

Keep `--voice-processing` only for macOS helper launches that include a microphone (`mic`, `mix`); leave Windows unchanged.

- [ ] **Step 4: Run bridge regression tests and syntax check**

Run:

```bash
python3 -m unittest tests/test_microphone_modes.py
python3 -m py_compile app.py
```

Expected: both commands exit 0.

### Task 3: Recording-time microphone-mode control

**Files:**
- Modify: `index.html:1249-1335, 2140-2150, 2364-2405, 2799-2825`
- Test: `tests/recording-shortcut.test.js`

**Interfaces:**
- Consumes: browser state `state`, selected source value, and `api('/api/microphone_modes', {mode: 'mic'})`.
- Produces: a visible, enabled “麦克风模式…” button only while a macOS 12+ mic recording is active; it does not render mode choices itself.

- [ ] **Step 1: Add a failing UI behavior test**

```javascript
test('microphone mode action calls the backend only during mic recording', async () => {
  const calls = [];
  const request = async (path, body) => { calls.push([path, body]); return {ok: true}; };
  await openMicrophoneModes({state: 'recording', mode: 'mic', request});
  assert.deepEqual(calls, [['/api/microphone_modes', {mode: 'mic'}]]);
});
```

Extract the small click handler into `openMicrophoneModes` in the existing inline script so this test evaluates real page behavior without a browser.

- [ ] **Step 2: Run the UI test to verify it fails**

Run: `node --test tests/recording-shortcut.test.js`

Expected: FAIL because the action and helper do not exist.

- [ ] **Step 3: Add the recording-control button and handler**

```html
<button class="micmodebtn" id="btnMicModes" hidden type="button">麦克风模式…</button>
```

Place it beside the existing recording pill. In the state-rendering function, set `hidden` unless `state === 'recording' && selectedMode === 'mic' && navigator.platform.includes('Mac')`; on click call `api('/api/microphone_modes', {mode: 'mic'})` and show the returned error through the existing `toast` helper. Do not implement a custom mode selector.

- [ ] **Step 4: Run UI tests**

Run: `node --test tests/recording-shortcut.test.js`

Expected: all tests pass.

### Task 4: End-to-end build and package verification

**Files:**
- Modify: generated `/Users/ayin/Applications/听道-测试版.app/Contents/MacOS/tingdao-mix` only after source verification
- Test: `tests/test_microphone_modes.py`, `tests/recording-shortcut.test.js`

**Interfaces:**
- Consumes: compiled `tingdao-mix`, test application identifier `local.tingdao.test`, and the source-root backend used by the test shell.
- Produces: a signed helper that the test app uses for `mic` recordings.

- [ ] **Step 1: Build and run all automated checks**

Run:

```bash
python3 -m unittest tests/test_microphone_modes.py
python3 -m py_compile app.py
node --test tests/recording-shortcut.test.js
swiftc tingdao-mix.swift -o tingdao-mix -framework ScreenCaptureKit -framework AVFoundation -framework CoreMedia -framework CoreAudio -framework AudioToolbox
git diff --check
```

Expected: every command exits 0; pre-existing Swift warnings may remain, but no Swift errors are allowed.

- [ ] **Step 2: Install and validate the signed test helper**

Run:

```bash
test_bundle='/Users/ayin/Applications/听道-测试版.app'
cp -f tingdao-mix "$test_bundle/Contents/MacOS/tingdao-mix"
codesign --force --sign - --identifier local.tingdao.test "$test_bundle/Contents/MacOS/tingdao-mix"
codesign --verify --strict --verbose=2 "$test_bundle/Contents/MacOS/tingdao-mix"
```

Expected: code-sign verification reports the helper as valid.

- [ ] **Step 3: Perform manual acceptance after a full test-app restart**

1. Choose “仅麦克风” and begin recording.
2. Confirm normal speech produces live transcript/audio.
3. Click “麦克风模式…”, choose a macOS-provided mode, and return to recording.
4. Stop and replay the recording to confirm it contains speech.
5. Confirm `system` and `mix` recordings do not expose the control.

- [ ] **Step 4: Commit only task-owned source and test files**

```bash
git add app.py tingdao-mix.swift index.html tests/test_microphone_modes.py tests/recording-shortcut.test.js docs/superpowers/specs/2026-09-20-macos-microphone-modes-design.md docs/superpowers/plans/2026-09-20-macos-microphone-modes.md
git commit -m "feat: add native macOS microphone modes"
```

Do not stage unrelated existing modifications or generated application artifacts.
