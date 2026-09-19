// tingdao-mix.swift — 听道 macOS 系统级音频采集助手（替代 BlackHole 虚拟声卡方案）
//
// 系统声音: ScreenCaptureKit（需屏幕录制权限；filter 必含一个显示器，视频压 2x2 占位）
// 麦克风:   AVAudioEngine（走宿主 app 已有的麦克风权限）
// 混音:     进程内实时相加(限幅)，输出 s16le/16kHz/单声道 —— 与原 ffmpeg avfoundation
//           的 stdout 协议逐字节一致，Python 侧 _read_loop/_finish 零改动。
//
// 用法: tingdao-mix --mode mix|system --rate 16000
//   mode=mix     系统声音 + 麦克风
//   mode=system  仅系统声音
// 退出: SIGINT/SIGTERM 优雅停止（flush 后退出 0）
// 起动失败向 stderr 打中文原因并退出非 0（[sckmix] ready 打出后 Python 才认为就绪）
import Foundation
import ScreenCaptureKit
import CoreMedia
import CoreAudio
import AudioToolbox
import AVFoundation

// ---------- 线程安全 FIFO ----------
final class Fifo {
    private let lk = NSLock()
    private var buf: [Float] = []
    func push(_ s: [Float]) { lk.lock(); buf.append(contentsOf: s); lk.unlock() }
    /// 取 n 个样本，不足补零（时钟漂移的零头以静音填，不入正文）
    func pop(_ n: Int) -> [Float] {
        lk.lock(); defer { lk.unlock() }
        if buf.count >= n {
            let out = Array(buf[0..<n]); buf.removeFirst(n); return out
        }
        let out = buf + [Float](repeating: 0, count: n - buf.count)
        buf.removeAll(); return out
    }
    func drain() -> [Float] { lk.lock(); defer { lk.unlock() }; let o = buf; buf.removeAll(); return o }
}

// ---------- SCK 抓系统声 ----------
final class SysGrabber: NSObject, SCStreamOutput, SCStreamDelegate {
    let fifo = Fifo()
    let q = DispatchQueue(label: "sck-audio")
    var frames = 0
    func stream(_ s: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of t: SCStreamOutputType) {
        guard t == .audio, CMSampleBufferDataIsReady(sb) else { return }
        frames += 1
        guard let bb = CMSampleBufferGetDataBuffer(sb) else { return }
        var lenAtOff = 0, total = 0
        var ptr: UnsafeMutablePointer<CChar>?
        // 实测(macOS 27): 音频 sample buffer 的 block buffer 整体就是裸 f32 PCM，
        // 20ms/帧，无 ABL 头。SCK 已按请求的采样率/声道转好格式。
        guard (try? CMBlockBufferGetDataPointer(bb, atOffset: 0, lengthAtOffsetOut: &lenAtOff,
                totalLengthOut: &total, dataPointerOut: &ptr)) == kCMBlockBufferNoErr,
              let base = ptr, total > 0 else { return }
        let floats = UnsafeRawPointer(base).assumingMemoryBound(to: Float.self)
        fifo.push(Array(UnsafeBufferPointer(start: floats, count: total / 4)))
    }
}

// ---------- 全局状态 ----------
var gStopFlag: Int32 = 0   // 信号处理器只置这个 flag(async-signal-safe)
var gSys: SysGrabber?
var gStream: SCStream?
var gEngine: AVAudioEngine?
var gMicFifo = Fifo()
var gOut: FileHandle = .standardOutput
let gOutLK = NSLock()
var gMode = "mix"
var gRate = 16000
var gMicName = ""

func log(_ s: String) { fputs("[sckmix] \(s)\n", stderr) }
func fail(_ s: String, _ code: Int32) -> Never { log(s); exit(code) }

func writeS16(_ samples: [Float]) {
    var out = [Int16](repeating: 0, count: samples.count)
    for (i, v) in samples.enumerated() {
        let c = max(-1.0, min(1.0, v))
        out[i] = Int16(c * 32767.0)
    }
    out.withUnsafeBytes { raw in
        gOutLK.lock(); gOut.write(Data(raw)); gOutLK.unlock()
    }
}

// ---------- 麦克风 ----------
// 设置里手动指定的麦克风按名字匹配(子串、忽略大小写); 名字对不上回落系统默认输入。
// 设备必须在 engine 起动前用 kAudioOutputUnitPropertyDevice 指定(macOS 才支持)。
func inputDeviceList() -> [(id: AudioDeviceID, name: String)] {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject),
            &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioDeviceID](repeating: 0,
            count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
            &addr, 0, nil, &size, &ids) == noErr else { return [] }
    var out: [(AudioDeviceID, String)] = []
    for id in ids {
        var saddr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreams,
                mScope: kAudioObjectPropertyScopeInput, mElement: kAudioObjectPropertyElementMain)
        var ss: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(id, &saddr, 0, nil, &ss) == noErr, ss > 0 else { continue }
        var name: CFString?
        var naddr = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName,
                mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var ns: UInt32 = UInt32(MemoryLayout<CFString?>.size)
        let ok = withUnsafeMutablePointer(to: &name) { p in
            AudioObjectGetPropertyData(id, &naddr, 0, nil, &ns, p)
        }
        guard ok == noErr, let n = name else { continue }
        out.append((id, n as String))
    }
    return out
}

func startMic(_ micName: String) {
    let engine = AVAudioEngine()
    if !micName.isEmpty {
        let devs = inputDeviceList()
        let hit = devs.first { $0.name.lowercased().contains(micName.lowercased()) }
        if let d = hit, let au = engine.inputNode.audioUnit {
            var did = d.id
            let st = AudioUnitSetProperty(au,
                    kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0,
                    &did, UInt32(MemoryLayout<AudioDeviceID>.size))
            log(st == noErr ? "mic device → \(d.name)" : "指定麦克风失败(\(st))，用默认输入")
        } else {
            log("找不到名为「\(micName)」的输入设备，用默认输入")
        }
    }
    let inNode = engine.inputNode
    let inFmt = inNode.outputFormat(forBus: 0)
    guard inFmt.sampleRate > 0, inFmt.channelCount > 0 else {
        fail("麦克风不可用（没有输入设备）", 5)
    }
    guard let outFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                     sampleRate: Double(gRate), channels: 1, interleaved: false) else {
        fail("内部错误：目标格式创建失败", 6)
    }
    guard let conv = AVAudioConverter(from: inFmt, to: outFmt) else {
        fail("内部错误：麦克风格式转换器创建失败", 6)
    }
    inNode.installTap(onBus: 0, bufferSize: 4096, format: inFmt) { buf, _ in
        let ratio = Double(gRate) / inFmt.sampleRate
        let cap = AVAudioFrameCount(Double(buf.frameLength) * ratio) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: outFmt, frameCapacity: cap) else { return }
        var fed = false
        var cerr: NSError?
        conv.convert(to: out, error: &cerr) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return buf
        }
        if out.frameLength > 0, let ch = out.floatChannelData?[0] {
            gMicFifo.push(Array(UnsafeBufferPointer(start: ch, count: Int(out.frameLength))))
        }
    }
    engine.prepare()
    do { try engine.start() } catch {
        fail("麦克风启动失败: \(error.localizedDescription)（检查麦克风权限）", 5)
    }
    gEngine = engine
    log("mic ok sr=\(inFmt.sampleRate) ch=\(inFmt.channelCount)")
}

// ---------- 混音泵: 每 20ms 出一拍 ----------
var pumpSrc: DispatchSourceTimer?

func startPump() {
    let tick = 320  // 20ms @16k
    let t = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "pump"))
    t.schedule(deadline: .now() + DispatchTimeInterval.milliseconds(20),
               repeating: .milliseconds(20))
    t.setEventHandler {
        if gStopFlag != 0 {
            pumpSrc?.cancel()
            flushAndExit()
            return
        }
        var mix: [Float]
        switch gMode {
        case "system":
            mix = gSys!.fifo.pop(tick)
        default:  // mix: 相加限幅（两路都常用语音电平, 削波罕见; 后续 loudnorm 兜底）
            let a = gSys!.fifo.pop(tick)
            let b = gMicFifo.pop(tick)
            mix = zip(a, b).map { $0 + $1 }
        }
        writeS16(mix)
    }
    t.resume()
    pumpSrc = t
}

func flushAndExit() -> Never {
    // 停止前把两路残余一次性混完（长度不齐补零）
    let sys = gSys?.fifo.drain() ?? []
    let mic = gMode == "mix" ? gMicFifo.drain() : []
    let n = max(sys.count, mic.count)
    if n > 0 {
        var mix = [Float](repeating: 0, count: n)
        if gMode == "mix" {
            for i in 0..<n { mix[i] = (i < sys.count ? sys[i] : 0) + (i < mic.count ? mic[i] : 0) }
        } else {
            for i in 0..<n { mix[i] = sys[i] }
        }
        writeS16(mix)
    }
    gOutLK.lock(); gOut.closeFile(); gOutLK.unlock()   // stdout 关闭 = 告诉 Python 读取结束
    exit(0)
}

// ---------- 信号: SIGINT/SIGTERM → 置 flag, 主循环轮询后优雅退出 ----------
// 不用 DispatchSource 信号源: 实测从 shell 派生的后台进程上它有时吞掉第一次 SIGINT
// (stop 按钮必须 100% 可靠)。裸 signal+flag 是唯一无竞态的做法。
func sigHandler(_ s: Int32) { gStopFlag = 1 }

func installSignals() {
    signal(SIGINT, sigHandler)
    signal(SIGTERM, sigHandler)
}

// ---------- main ----------
let args = CommandLine.arguments
var i = 1
while i < args.count {
    switch args[i] {
    case "--mode": i += 1; gMode = i < args.count ? args[i] : "mix"
    case "--rate": i += 1; gRate = i < args.count ? Int(args[i]) ?? 16000 : 16000
    case "--mic":  i += 1; gMicName = i < args.count ? args[i] : ""
    default: break
    }
    i += 1
}
guard gMode == "mix" || gMode == "system" else { fail("未知模式 \(gMode)", 2) }
guard gRate > 4000 && gRate <= 96000 else { fail("非法采样率 \(gRate)", 2) }

// 1. SCK 起流（缺屏幕录制权限时 displays 为空/抛错 → 中文报错）
let content: SCShareableContent
do {
    content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
} catch {
    fail("无法枚举屏幕内容: \(error.localizedDescription)（检查屏幕录制权限）", 3)
}
guard let display = content.displays.first else {
    fail("缺少屏幕录制权限：系统设置 → 隐私与安全性 → 屏幕录制，允许听道后重试", 4)
}
let filter = SCContentFilter(display: display, excludingWindows: [])
let cfg = SCStreamConfiguration()
cfg.capturesAudio = true
cfg.sampleRate = gRate
cfg.channelCount = 1
cfg.excludesCurrentProcessAudio = true
cfg.width = 2; cfg.height = 2
cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
cfg.queueDepth = 3

let grabber = SysGrabber()
let stream = SCStream(filter: filter, configuration: cfg, delegate: grabber)
do {
    try stream.addStreamOutput(grabber, type: .audio, sampleHandlerQueue: grabber.q)
    try await stream.startCapture()
} catch {
    fail("系统声音流启动失败: \(error.localizedDescription)", 5)
}
gSys = grabber
gStream = stream
log("sys ok rate=\(gRate)")

// 2. 麦克风（mix 模式才启用）
if gMode == "mix" { startMic(gMicName) }

// 3. 信号 + 混音泵, 主线程挂起等待 gStop
installSignals()
startPump()
log("ready")
while gStopFlag == 0 { usleep(100_000) }
flushAndExit()
