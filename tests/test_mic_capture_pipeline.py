import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "app.py"
HELPER = ROOT / "tingdao-mix.swift"


class MicrophoneCapturePipelineTests(unittest.TestCase):
    def test_mic_recording_writes_vpio_frames_to_a_ring_buffer(self):
        """VPIO 回调只写环形缓冲，重采样和写盘不在实时回调内。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("// 2. 仅麦克风由")
        end = source.index("// 3. 信号", start)
        startup = source[start:end]
        self.assertIn('if gMode == "mic" { bootstrapAppKit(); startVpioMic(gMicName); diagBanner() }', startup)
        self.assertIn("final class MicRingBuffer", source)
        callback_start = source.index("let vpioInputRender")
        callback_end = source.index("func microphoneModeName", callback_start)
        callback = source[callback_start:callback_end]
        self.assertIn("gMicRing.writeMono", callback)
        self.assertNotIn("gMicFifo.push(mono)", callback)
        self.assertNotIn("resampleMicBlock", callback)
        writer_start = source.index("func startMicWriter()")
        writer_end = source.index("func startPump()", writer_start)
        writer = source[writer_start:writer_end]
        self.assertIn("gMicRing.waitRead", writer)
        self.assertNotIn("Thread.sleep", writer)

    def test_mic_writer_preserves_native_rate_master_before_resampling(self):
        """VPIO 原始帧必须在写盘线程先落为母带，再生成 16k 转写流。"""
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn('case "--master"', source)
        self.assertIn('case "--master-rate-file"', source)
        self.assertIn("func writeMasterS16", source)
        writer_start = source.index("func startMicWriter()")
        writer_end = source.index("func startPump()", writer_start)
        writer = source[writer_start:writer_end]
        self.assertIn("writeMasterS16(src)", writer)
        self.assertLess(writer.index("writeMasterS16(src)"), writer.index("resampleMicBlock(src)"))
        callback_start = source.index("let vpioInputRender")
        callback_end = source.index("func microphoneModeName", callback_start)
        self.assertNotIn("writeMasterS16", source[callback_start:callback_end])

    def test_vpio_callback_uses_preallocated_render_buffers(self):
        """实时回调不能为每个音频块分配或释放堆内存。"""
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("func prepareVpioRenderBuffers", source)
        callback_start = source.index("let vpioInputRender")
        callback_end = source.index("func microphoneModeName", callback_start)
        callback = source[callback_start:callback_end]
        self.assertIn("gVpioRenderList", callback)
        self.assertNotIn("UnsafeMutableRawPointer.allocate", callback)
        self.assertNotIn("deallocate", callback)

    def test_master_file_closes_only_after_writer_drains_ring(self):
        """停止录音时不能在写盘线程仍在排空环形缓冲时关闭母带文件。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("func flushAndExit()")
        end = source.index("// ---------- 信号", start)
        body = source[start:end]
        self.assertIn("gMicWriterDone?.wait()", body)
        self.assertNotIn("gMicWriterDone?.wait(timeout:", body)

    def test_vpio_callback_resets_reused_render_buffer_capacity(self):
        """AudioUnitRender 会缩小 mDataByteSize；下次回调前必须恢复预分配容量。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("let vpioInputRender: AURenderCallback")
        end = source.index("func startVpioMic", start)
        body = source[start:end]
        self.assertIn("resetVpioRenderByteSizes(frames)", body)

    def test_vpio_callback_matches_buffer_byte_size_to_requested_frames(self):
        """复用大缓冲时，mDataByteSize 仍须匹配本次 AudioUnitRender 的帧数。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("let vpioInputRender: AURenderCallback")
        end = source.index("func startVpioMic", start)
        body = source[start:end]
        self.assertIn("resetVpioRenderByteSizes(frames)", body)

    def test_vpio_uses_separate_input_capture_and_output_silence_callbacks(self):
        """VPIO 输入采集必须走 input callback，不能在输出回调里兼做拉取。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("func startVpioMic")
        end = source.index("// ---------- 仅麦克：事件驱动写盘 ----------", start)
        body = source[start:end]
        self.assertIn("vpioInputRender", body)
        self.assertIn("vpioOutputSilence", body)
        self.assertIn("kAudioOutputUnitProperty_SetInputCallback", body)
        self.assertIn("kAudioUnitScope_Global, 1", body)

    def test_vpio_microphone_capture_disables_automatic_gain_control(self):
        """高保真母带不能由 VPIO 的 AGC 自动抬高人声与底噪。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("func startVpioMic")
        end = source.index("// ---------- 仅麦克：事件驱动写盘 ----------", start)
        body = source[start:end]
        self.assertIn("kAUVoiceIOProperty_VoiceProcessingEnableAGC", body)
        self.assertIn("var agcEnabled: UInt32 = 0", body)

    def test_resampler_keeps_frames_when_converter_input_runs_dry(self):
        """AVAudioConverter may return inputRanDry together with valid output frames."""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("func popMic(")
        end = source.index("func gMicFifoTakePadded", start)
        body = source[start:end]
        self.assertIn("outBuf.frameLength > 0", body)
        self.assertNotIn("st == .haveData || st == .endOfStream", body)

    def test_pcm_reader_does_not_run_recognition_inline(self):
        """A slow recognizer must never stop the FIFO reader from draining PCM."""
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        app = next(node for node in tree.body
                   if isinstance(node, ast.ClassDef) and node.name == "App")
        methods = {node.name: node for node in app.body if isinstance(node, ast.FunctionDef)}

        reader_calls = [node for node in ast.walk(methods["_read_loop"])
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
        self.assertNotIn("_feed", [node.func.attr for node in reader_calls])
        self.assertIn("_decode_loop", methods)
        self.assertIn("_pcm_q", ast.unparse(methods["_read_loop"]))
        self.assertIn("self.capture_lock", ast.unparse(methods["_read_loop"]))

    def test_pcm_reader_keeps_pending_stop_tail(self):
        """SIGINT 后仍要排空已进入命名管道的 PCM，不能截掉结尾。"""
        source = ast.unparse(ast.parse(APP.read_text(encoding="utf-8")))
        reader_start = source.index("def _read_loop(self):")
        reader_end = source.index("def _decode_loop", reader_start)
        body = source[reader_start:reader_end]
        self.assertIn("self._pending_ff is not ff", body)

    def test_mic_helper_is_registered_and_launched_as_an_app(self):
        """Mic Modes require the helper to stay a LaunchServices app, not a bare process."""
        source = APP.read_text(encoding="utf-8")
        start = source.index("    def _spawn_mic_app(self):")
        end = source.index("    def _start_recorder(self, mode):", start)
        body = source[start:end]
        self.assertIn("lsregister", body)
        self.assertIn('["open", "-n", str(MIC_APP), "--args", *helper_args]', body)
        self.assertNotIn('MIC_APP / "Contents" / "MacOS" / "TingdaoMic"', body)

    def test_mix_has_headroom_before_pcm_conversion(self):
        """混录必须先留余量，不能把两路相加后再硬截断成滋滋声。"""
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("func mixWithHeadroom", source)
        self.assertIn("mix = mixWithHeadroom(a, b)", source)
        self.assertNotIn("mix = zip(a, b).map { $0 + $1 }", source)

    def test_resampler_does_not_turn_partial_fifo_reads_into_zero_gaps(self):
        """VPIO 回调有抖动时只取现有帧，不能 pop() 补零后丢掉真实帧。"""
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("func take(_ n: Int)", source)
        self.assertIn("let src = gMicFifo.take(want)", source)
        self.assertNotIn("let src = gMicFifo.pop(want)", source)
        fallback_start = source.index("func linearFallback")
        fallback_end = source.index("var gLinBuf", fallback_start)
        self.assertIn("gMicFifo.take(", source[fallback_start:fallback_end])

    def test_vpio_reports_source_block_boundary_discontinuities(self):
        """真人麦克验收发现 512 帧边界爆点，助手必须输出可核验的源头指标。"""
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("gVpioBoundaryMaxStep", source)
        self.assertIn("gVpioBoundaryStepCount", source)
        self.assertIn("boundaryMaxStep", source)

    def test_mic_writer_is_event_driven_and_never_zero_pads_underflow(self):
        """仅麦克必须按可用帧写盘，不能靠 20ms 泵和补零伪造时钟。"""
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("func startMicWriter()", source)
        writer_start = source.index("func startMicWriter()")
        writer_end = source.index("func startPump()", writer_start)
        writer = source[writer_start:writer_end]
        self.assertIn("gMicRing.waitRead", writer)
        self.assertNotIn("Thread.sleep", writer)
        pump_start = source.index("func startPump()")
        pump_end = source.index("func flushAndExit", pump_start)
        self.assertIn('if gMode == "mic" { startMicWriter(); return }', source[pump_start:pump_end])


    def test_native_mic_panel_activates_appkit_before_showing(self):
        """Mic Modes 面板必须由当前 AppKit 应用激活后再请求系统 UI。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("func showMicrophoneModes()")
        end = source.index("// ---------- main ----------", start)
        body = source[start:end]
        self.assertIn("NSApplication.shared.activate(ignoringOtherApps: true)", body)

    def test_main_loop_pumps_appkit_runloop_for_native_panel(self):
        """AppKit 的非阻塞原生面板请求必须由主 RunLoop 实际派发。"""
        source = HELPER.read_text(encoding="utf-8")
        start = source.index("func runMainLoop()")
        end = source.index("runMainLoop()", start + len("func runMainLoop()"))
        body = source[start:end]
        self.assertIn("while gStopFlag == 0", body)
        self.assertIn("RunLoop.main.run(until:", body)
        self.assertNotIn("usleep(100_000)", body)

    def test_recording_keeps_lossless_playback_master(self):
        """回放优先使用无损 WAV；AAC 只作为识别/兼容副本。"""
        source = APP.read_text(encoding="utf-8")
        self.assertIn('master = d / "audio.wav"', source)
        self.assertIn('LISTEN_FILE = "audio_listen.wav"', source)
        self.assertIn("listen_rel = master.name", source)
        self.assertIn('".wav": "audio/wav"', source)
        self.assertIn('d.glob("*.wav")', source)
        self.assertIn('"-c:a", "aac", "-b:a", "96k"', source)

    def test_playback_noise_filter_does_not_loudness_boost_noise(self):
        """默认回放降噪不能再用 loudnorm 把底噪整体抬高。"""
        source = APP.read_text(encoding="utf-8")
        start = source.index('LISTEN_FILTER = ')
        end = source.index("\n", start)
        self.assertNotIn("loudnorm", source[start:end])

    def test_default_playback_uses_unprocessed_lossless_master(self):
        """试听必须选原始 WAV，不能把频谱降噪副本当作默认声音。"""
        source = APP.read_text(encoding="utf-8")
        start = source.index("    def load(self, sid):")
        end = source.index("    @staticmethod\n    def _read_pref", start)
        body = source[start:end]
        self.assertIn('meta.get("audioMaster")', body)
        self.assertIn('master = "audio.wav"', body)
        self.assertIn("play = master if master else", body)


if __name__ == "__main__":
    unittest.main()
