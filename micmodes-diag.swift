// micmodes-diag.swift — 听道麦克风模式【独立诊断版】（不接入业务，不改 app.py/main.rs）
//
// 目的：验证 Apple 官方 Mic Modes 要求的 AUVoiceIO 路径在本机是否真正生效。
// 官方依据 WWDC21 Session 10047 "What's new in camera capture" 原文：
//   "In order to use Mic Modes, your app must adopt the Core Audio AUVoiceIO audio unit."
//   "Mic Mode processing is only available on 2018 and later iOS and macOS devices."
//   "These flavors can only be set by the user in Control Center, but you can read and
//    observe their state using AVCaptureDevice's preferredMicrophoneMode -- which is the
//    mode selected by the user -- and activeMicrophoneMode -- which is the mode now in use,
//    taking into account the current audio route, which may not support the user's
//    preferred Mic Mode."
// 结论：AVCaptureSession + AVCaptureAudioDataOutput 不在官方 Mic Modes 处理路径内。
//
// 本诊断版音频链路（不经 AVAudioEngine）：
//   物理麦克风 → AUVoiceProcessingIO (kAudioUnitSubType_VoiceProcessingIO)
//             → 输出端渲染回调中 AudioUnitRender(element 1) 拉取 PCM
//             → FIFO → 按 activeMicrophoneMode 自动分段写 WAV
//
// 系统面板入口保留：SIGUSR1 → AVCaptureDevice.showSystemUserInterface(.microphoneModes)
// 模式由用户在系统 UI 里切换，程序绝不私设。
//
// 用法: micmodes-diag [--rate 16000] [--out-dir DIR] [--secs N] [--delay-start N] [--mic NAME]
//   --rate        WAV 输出采样率（默认 16000；VPIO 客户端格式实测锁 44.1kHz，
//                 预设 16k/48k 会让 init 失败，故内部线性重采样到该值）
//   --out-dir     WAV 输出目录（默认 ./micmodes-diag-out）
//   --secs        N 秒后自动停止（默认 0 = 手动 Ctrl-C / SIGTERM 停）
//   --delay-start 先等 N 秒再启动 VPIO（此期间可发 SIGUSR1 实测「未激活麦克风时
//                 能否打开系统面板」——回答 NSAlwaysAllowMicrophoneModeControl 在
//                 macOS 上想解决的同一问题；该键官方仅 iOS18+/iPadOS18+，macOS 无）
//   --mic         按名字子串选输入设备（找不到回落默认，如实打日志）
// 退出: SIGINT/SIGTERM 优雅停止；启动失败 stderr 中文原因 + 非零退出码
//
// 注意：首次运行 macOS 会弹麦克风权限（主体=本二进制），需要点允许。

import Foundation
import AppKit
import CoreAudio
import AudioToolbox
import AVFoundation

// ---------- 全局状态 ----------
var gStopFlag: Int32 = 0   // 信号处理器只置 flag(async-signal-safe)
var gShowUIFlag: Int32 = 0
var gTargetRate: Double = 16000
var gSecs: Double = 0
var gDelayStart: Double = 0
var gOutDir = "micmodes-diag-out"
var gMicName = ""
var gActivate = false          // --activate：把本进程变成前台 App（验证「面板只为前台 App 打开」）

func frontmostName() -> String {
    NSWorkspace.shared.frontmostApplication?.localizedName ?? "?"
}

/// 自激活：无窗口的可执行文件也能成为前台 App，用于隔离「前台与否」这个变量
func bringSelfToFront(_ tag: String) {
    guard gActivate else { return }
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.activate(ignoringOtherApps: true)
    for _ in 0..<20 {
        CFRunLoopRunInMode(.defaultMode, 0.03, false)
        if frontmostName() != "千问办公" { break }
    }
    log("自激活[\(tag)] → 当前前台=\(frontmostName())")
}

var gUnit: AudioComponentInstance?
var gActualRate: Double = 0        // element1 实际客户端采样率（WAV 头用这个）
var gActualChannels: Int = 1
var gNonInterleaved = false
var gRenderErr: OSStatus = 0       // 最近一次 AudioUnitRender 错误
var gRenderErrCount = 0
var gSilenceFlagFrames = 0         // 回调置了 outputIsSilence 的帧数

let gFifoLK = NSLock()
var gFifo = [Float]()
var gCbCount = 0                   // 拉取回调次数
var gPulledSamples = 0             // 累计采样数（mono，VPIO 原生率）
var gPeak: Float = 0               // 峰值（0~1）
var gWritten = 0                   // 重采样后写入 WAV 的样本数
let gT0 = Date()

func log(_ s: String) {
    fputs(String(format: "[mm-diag][%7.3fs] %@\n", Date().timeIntervalSince(gT0), s), stderr)
}
func fail(_ s: String, _ code: Int32) -> Never { log(s); exit(code) }

// ---------- 线性重采样（VPIO 原生 44.1k → 目标采样率，带跨缓冲相位连续） ----------
var gResPos = 0.0     // 下一输出点在输入序列中的小数偏移（相对新缓冲首样本，可到 step）
var gResLast: Float = 0
func resample(_ x: [Float], from: Double, to: Double) -> [Float] {
    if abs(from - to) < 0.5 || x.isEmpty { return x }
    // seq[0]=上一缓冲末样本, seq[1...]=x；输出点 i 从 gResPos 起步、每点推进 from/to
    var seq = x
    seq.insert(gResLast, at: 0)
    let step = from / to
    var i = gResPos
    if i < 0 { i = 0 }
    var out: [Float] = []
    out.reserveCapacity(Int(Double(x.count) * to / from) + 8)
    let top = Double(seq.count - 1)
    while i < top {
        let idx = Int(i)
        let frac = Float(i - Double(idx))
        out.append(seq[idx] + (seq[idx + 1] - seq[idx]) * frac)
        i += step
    }
    gResPos = i - top          // 落在 [0, step)
    gResLast = x[x.count - 1]
    return out
}

// ---------- WAV 写出 ----------
final class WavWriter {
    let url: URL
    private var fh: FileHandle?
    private(set) var dataBytes: UInt32 = 0
    private let rate: Int

    private func le16(_ v: UInt16) -> [UInt8] { [UInt8(v & 0xff), UInt8((v >> 8) & 0xff)] }
    private func le32(_ v: UInt32) -> [UInt8] {
        [UInt8(v & 0xff), UInt8((v >> 8) & 0xff), UInt8((v >> 16) & 0xff), UInt8((v >> 24) & 0xff)]
    }

    init?(path: URL, rate: Int) {
        self.url = path
        self.rate = rate
        FileManager.default.createFile(atPath: path.path, contents: nil)
        guard let h = FileHandle(forWritingAtPath: path.path) else { return nil }
        fh = h
        var hdr = Data()
        hdr.append(contentsOf: Array("RIFF".utf8)); hdr.append(contentsOf: le32(0))
        hdr.append(contentsOf: Array("WAVE".utf8))
        hdr.append(contentsOf: Array("fmt ".utf8)); hdr.append(contentsOf: le32(16))
        hdr.append(contentsOf: le16(1))                    // PCM
        hdr.append(contentsOf: le16(1))                    // mono
        hdr.append(contentsOf: le32(UInt32(rate)))
        hdr.append(contentsOf: le32(UInt32(rate) * 2))     // byte rate
        hdr.append(contentsOf: le16(2))                    // block align
        hdr.append(contentsOf: le16(16))                   // bits
        hdr.append(contentsOf: Array("data".utf8)); hdr.append(contentsOf: le32(0))
        h.write(hdr)
    }

    func write(_ samples: [Float]) {
        guard let h = fh, !samples.isEmpty else { return }
        var out = [Int16](repeating: 0, count: samples.count)
        for (i, v) in samples.enumerated() {
            out[i] = Int16(max(-1.0, min(1.0, v)) * 32767.0)
        }
        out.withUnsafeBytes { h.write(Data($0)) }
        dataBytes &+= UInt32(samples.count) * 2
    }

    func close() {
        guard let h = fh else { return }
        h.seek(toFileOffset: 4); h.write(Data(le32(36 + dataBytes)))
        h.seek(toFileOffset: 40); h.write(Data(le32(dataBytes)))
        h.closeFile()
        fh = nil
    }
}

var gSeg: WavWriter?
var gSegMode = ""

func closeSegment() {
    guard let s = gSeg else { return }
    s.close()
    if s.dataBytes == 0 {
        try? FileManager.default.removeItem(at: s.url)
        log("分段[\(gSegMode)] 无数据，已删除空文件")
    } else {
        log("分段[\(gSegMode)] 收笔：\(s.dataBytes) 字节（\(String(format: "%.1f", Double(s.dataBytes) / 2.0 / gTargetRate))s）→ \(s.url.lastPathComponent)")
    }
    gSeg = nil
}

func openSegment(_ mode: String) {
    let df = DateFormatter(); df.dateFormat = "HHmmss"
    let url = URL(fileURLWithPath: gOutDir).appendingPathComponent("diag-\(mode)-\(df.string(from: Date())).wav")
    guard let w = WavWriter(path: url, rate: Int(gTargetRate)) else {
        log("无法创建分段文件 \(url.path)"); return
    }
    gSeg = w; gSegMode = mode
    log("分段[\(mode)] 开笔 → \(url.lastPathComponent) rate=\(Int(gTargetRate))（VPIO 原生 \(Int(gActualRate)) 重采样而来）")
}

// ---------- 麦克风模式读取（只读，绝不私设） ----------
func prefModeName() -> String {
    guard #available(macOS 12.0, *) else { return "n/a(<12.0)" }
    switch AVCaptureDevice.preferredMicrophoneMode {
    case .standard: return "standard"
    case .wideSpectrum: return "wideSpectrum"
    case .voiceIsolation: return "voiceIsolation"
    @unknown default: return "unknown"
    }
}
func actModeName() -> String {
    guard #available(macOS 12.0, *) else { return "n/a(<12.0)" }
    switch AVCaptureDevice.activeMicrophoneMode {
    case .standard: return "standard"
    case .wideSpectrum: return "wideSpectrum"
    case .voiceIsolation: return "voiceIsolation"
    @unknown default: return "unknown"
    }
}

// ---------- 输入设备枚举（与 tingdao-mix 同款逻辑） ----------
func inputDeviceList() -> [(id: AudioDeviceID, name: String)] {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject),
            &addr, 0, nil, &size) == noErr, size > 0 else { return [] }
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
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

// ---------- VPIO 拉取式渲染回调 ----------
// 输出端(element 0)被硬件拉取 → 本回调里把输出填静音、并 AudioUnitRender(element 1)
// 拉取麦克风 PCM。这是 WebRTC 在 macOS 生产环境的同款模式，不经 AVAudioEngine。
let renderProc: AURenderCallback = { _, ioActionFlags, inTimeStamp, inBusNumber, inNumberFrames, ioData in
    guard inBusNumber == 0, let ioData else { return noErr }

    // 1) 输出端静音（本诊断只采不播）
    let outN = Int(ioData.pointee.mNumberBuffers)
    if outN > 0 {
        let base = UnsafeMutableRawPointer(ioData) + (MemoryLayout.offset(of: \AudioBufferList.mBuffers) ?? 16)
        let bufs = base.assumingMemoryBound(to: AudioBuffer.self)
        for i in 0..<outN {
            if let d = bufs[i].mData, bufs[i].mDataByteSize > 0 {
                memset(d, 0, Int(bufs[i].mDataByteSize))
            }
        }
    }

    // 2) 拉取输入
    guard let unit = gUnit, inNumberFrames > 0 else { return noErr }
    let ch = max(1, gActualChannels)
    let frames = Int(inNumberFrames)
    let ablSize = MemoryLayout<AudioBufferList>.size + (ch - 1) * MemoryLayout<AudioBuffer>.size
    let ablRaw = UnsafeMutableRawPointer.allocate(byteCount: ablSize, alignment: 8)
    let dataRaw = UnsafeMutableRawPointer.allocate(byteCount: frames * (gNonInterleaved ? 4 : 4 * ch), alignment: 8)
    defer { ablRaw.deallocate(); dataRaw.deallocate() }
    let listP = ablRaw.assumingMemoryBound(to: AudioBufferList.self)
    if gNonInterleaved {
        listP.pointee.mNumberBuffers = UInt32(ch)
        let bufBase = ablRaw + (MemoryLayout.offset(of: \AudioBufferList.mBuffers) ?? 16)
        for i in 0..<ch {
            let bp = (bufBase + i * MemoryLayout<AudioBuffer>.size).assumingMemoryBound(to: AudioBuffer.self)
            bp.pointee.mNumberChannels = 1
            bp.pointee.mDataByteSize = UInt32(frames * 4)
            bp.pointee.mData = dataRaw + i * frames * 4
        }
    } else {
        listP.pointee.mNumberBuffers = 1
        listP.pointee.mBuffers.mNumberChannels = UInt32(ch)
        listP.pointee.mBuffers.mDataByteSize = UInt32(frames * 4 * ch)
        listP.pointee.mBuffers.mData = dataRaw
    }
    var flags = AudioUnitRenderActionFlags(rawValue: 0)
    let st = AudioUnitRender(unit, &flags, inTimeStamp, 1, inNumberFrames, listP)
    if st != noErr {
        gRenderErr = st; gRenderErrCount += 1
        return noErr   // 不让整个 unit 失效
    }
    if flags.contains(.unitRenderAction_OutputIsSilence) { gSilenceFlagFrames += frames }

    // 3) 混成 mono Float（interleaved 多声道取均值；non-interleaved 只取 ch0，日志已注明）
    let f = dataRaw.assumingMemoryBound(to: Float.self)
    var mono = [Float](repeating: 0, count: frames)
    if gNonInterleaved {
        for i in 0..<frames { mono[i] = f[i] }
    } else if ch == 1 {
        for i in 0..<frames { mono[i] = f[i] }
    } else {
        for i in 0..<frames {
            var s: Float = 0
            for c in 0..<ch { s += f[i * ch + c] }
            mono[i] = s / Float(ch)
        }
    }
    var pk: Float = 0
    for v in mono where v > pk || -v > pk { pk = v > -v ? v : -v }
    gFifoLK.lock()
    gCbCount += 1
    gPulledSamples += frames
    if pk > gPeak { gPeak = pk }
    gFifo.append(contentsOf: mono)
    gFifoLK.unlock()
    return noErr
}

// ---------- 信号 ----------
func sigHandler(_ s: Int32) {
    if s == SIGUSR1 { gShowUIFlag = 1 } else { gStopFlag = 1 }
}
func installSignals() {
    signal(SIGINT, sigHandler)
    signal(SIGTERM, sigHandler)
    signal(SIGUSR1, sigHandler)
}

func showSystemMicModesUI() {
    if #available(macOS 12.0, *) {
        bringSelfToFront("调用面板前")
        log("调用 showSystemUserInterface(.microphoneModes) …（前台=\(frontmostName())）")
        AVCaptureDevice.showSystemUserInterface(.microphoneModes)
    } else {
        log("showSystemUserInterface 需要 macOS 12+")
    }
}

// ---------- VPIO 装配 ----------
func setupUnit() {
    var desc = AudioComponentDescription(
        componentType: kAudioUnitType_Output,
        componentSubType: kAudioUnitSubType_VoiceProcessingIO,
        componentManufacturer: kAudioUnitManufacturer_Apple,
        componentFlags: 0, componentFlagsMask: 0)
    guard let comp = AudioComponentFindNext(nil, &desc) else {
        fail("找不到 AUVoiceProcessingIO 组件", 10)
    }
    var unit: AudioComponentInstance?
    let st0 = AudioComponentInstanceNew(comp, &unit)
    guard st0 == noErr, let u = unit else { fail("创建 VPIO 实例失败 (\(st0))", 10) }
    gUnit = u

    // 启用输入 IO（element 1 默认关闭；输出端 element 0 默认开着，保持默认）
    var on: UInt32 = 1
    var st = AudioUnitSetProperty(u, kAudioOutputUnitProperty_EnableIO,
            kAudioUnitScope_Input, 1, &on, 4)
    guard st == noErr else { fail("启用 VPIO 输入 IO 失败 (\(st))", 10) }

    // 可选：按名字选输入设备（VPIO 对非默认设备的支持如实报错，回落默认）
    if !gMicName.isEmpty {
        let hit = inputDeviceList().first { $0.name.lowercased().contains(gMicName.lowercased()) }
        if let d = hit {
            var did = d.id
            st = AudioUnitSetProperty(u, kAudioOutputUnitProperty_CurrentDevice,
                    kAudioUnitScope_Input, 1, &did, UInt32(MemoryLayout<AudioDeviceID>.size))
            log(st == noErr ? "mic device → \(d.name)" : "指定麦克风失败(\(st))，用默认输入")
        } else {
            log("找不到名为「\(gMicName)」的输入设备，用默认输入")
        }
    }

    // 客户端格式：实测(macOS 27 本机) VPIO element1 锁定 44.1kHz/mono/Float32——
    // 预设任何其他采样率(16k/48k/stereo/Int16)都会让 AudioUnitInitialize 失败 -10875
    // (kAudioUnitErr_FailedInitialization)，uninit→set→re-init 也救不回。
    // 所以这里【不预设】，init 后读回实际格式，输出侧用线性重采样到 --rate。

    // 输出端渲染回调（element 0 input scope）：静音输出 + 拉取输入
    var cb = AURenderCallbackStruct(inputProc: renderProc, inputProcRefCon: nil)
    st = AudioUnitSetProperty(u, kAudioUnitProperty_SetRenderCallback,
            kAudioUnitScope_Input, 0, &cb, UInt32(MemoryLayout<AURenderCallbackStruct>.size))
    guard st == noErr else { fail("挂输出渲染回调失败 (\(st))", 10) }

    st = AudioUnitInitialize(u)
    guard st == noErr else { fail("VPIO 初始化失败 (\(st))", 10) }

    var got = AudioStreamBasicDescription()
    var sz = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    guard AudioUnitGetProperty(u, kAudioUnitProperty_StreamFormat,
            kAudioUnitScope_Output, 1, &got, &sz) == noErr else {
        fail("读回 element1 格式失败", 10)
    }
    gActualRate = got.mSampleRate
    gActualChannels = max(1, Int(got.mChannelsPerFrame))
    gNonInterleaved = (got.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0
    let layoutStr = gNonInterleaved ? "non-interleaved" : "interleaved"
    let fmtStr = (got.mFormatID == kAudioFormatLinearPCM) ? "LinearPCM" : "fmt=\(got.mFormatID)"
    var note = " bits=\(got.mBitsPerChannel)"
    if gNonInterleaved && gActualChannels > 1 { note += "（混音只取 ch0）" }
    log("element1 实际格式：\(Int(got.mSampleRate))Hz ch=\(gActualChannels) \(layoutStr) \(fmtStr)\(note)")

    log("VPIO 初始化完成，启动前模式：preferred=\(prefModeName()) active=\(actModeName())")
    st = AudioOutputUnitStart(u)
    guard st == noErr else { fail("VPIO 启动失败 (\(st))（检查麦克风权限）", 10) }
    log("VPIO 已启动，启动后模式：preferred=\(prefModeName()) active=\(actModeName())")
}

// ---------- main ----------
let args = CommandLine.arguments
var i = 1
while i < args.count {
    switch args[i] {
    case "--rate": i += 1; gTargetRate = i < args.count ? Double(args[i]) ?? 16000 : 16000
    case "--out-dir": i += 1; gOutDir = i < args.count ? args[i] : gOutDir
    case "--secs": i += 1; gSecs = i < args.count ? Double(args[i]) ?? 0 : 0
    case "--delay-start": i += 1; gDelayStart = i < args.count ? Double(args[i]) ?? 0 : 0
    case "--mic": i += 1; gMicName = i < args.count ? args[i] : ""
    case "--activate": gActivate = true
    case "--log":
        i += 1
        if i < args.count {
            let fd = open(args[i], O_WRONLY | O_CREAT | O_APPEND, 0o644)
            if fd >= 0 { dup2(fd, STDERR_FILENO); close(fd) }
        }
    default: break
    }
    i += 1
}

try? FileManager.default.createDirectory(atPath: gOutDir, withIntermediateDirectories: true)
log("micmodes-diag 启动 rate=\(Int(gTargetRate)) out=\(gOutDir) secs=\(gSecs) delay=\(gDelayStart) mic=\"\(gMicName)\"")
log("进程 pid=\(ProcessInfo.processInfo.processIdentifier)（SIGUSR1=开系统面板 / SIGINT=停止）")

installSignals()

if gDelayStart > 0 {
    log("延迟 \(gDelayStart)s 启动采集。此期间 VPIO 未激活，可实测「未录时打开面板」：kill -USR1 \(ProcessInfo.processInfo.processIdentifier)")
    let dl = Date().addingTimeInterval(gDelayStart)
    while Date() < dl && gStopFlag == 0 {
        if gShowUIFlag != 0 { gShowUIFlag = 0; showSystemMicModesUI() }
        usleep(100_000)
    }
    if gStopFlag != 0 { log("延迟期间收到停止信号，未启动采集"); exit(0) }
}

setupUnit()
bringSelfToFront("采集已启动")
openSegment(actModeName())
log("ready —— 请在系统面板里切换 Standard / Voice Isolation / Wide Spectrum（每次保持说话几秒，WAV 会按模式自动分段）")

var lastPref = prefModeName()
var lastAct = actModeName()
var lastStats = Date()
let unitStart = Date()

while gStopFlag == 0 {
    if gShowUIFlag != 0 { gShowUIFlag = 0; showSystemMicModesUI() }
    if gSecs > 0 && Date().timeIntervalSince(unitStart) >= gSecs {
        log("--secs \(gSecs) 到时，自动停止"); break
    }
    usleep(200_000)

    // 排干 FIFO：重采样到目标采样率后写当前分段
    gFifoLK.lock()
    let chunk = gFifo
    gFifo.removeAll()
    gFifoLK.unlock()
    if !chunk.isEmpty {
        let out = resample(chunk, from: gActualRate, to: gTargetRate)
        gSeg?.write(out)
        gWritten += out.count
    }

    let p = prefModeName(), a = actModeName()
    if p != lastPref {
        log("preferred 变化：\(lastPref) → \(p)")
        lastPref = p
    }
    if a != lastAct {
        log("active   变化：\(lastAct) → \(a)   ★ 分段切换")
        closeSegment()
        openSegment(a)
        lastAct = a
    }
    if Date().timeIntervalSince(lastStats) >= 2.0 {
        lastStats = Date()
        gFifoLK.lock()
        let fifoN = gFifo.count
        let cb = gCbCount, sp = gPulledSamples, pk = gPeak
        gFifoLK.unlock()
        log(String(format: "状态 preferred=%@ active=%@ callbacks=%d pulled=%d(%.1fs@%.0fk) written=%d(%.1fs@%.0fk) peak=%.4f fifo=%d renderErr=%d(err=%d) silenceFrames=%d",
                lastPref, lastAct, cb, sp, Double(sp) / gActualRate, gActualRate / 1000,
                gWritten, Double(gWritten) / gTargetRate, gTargetRate / 1000,
                pk, fifoN, gRenderErrCount, gRenderErr, gSilenceFlagFrames))
    }
}

// 收尾：排干 FIFO、关文件
gFifoLK.lock()
let drain = gFifo; gFifo.removeAll()
let cb = gCbCount, sp = gPulledSamples, pk = gPeak
gFifoLK.unlock()
if !drain.isEmpty {
    let out = resample(drain, from: gActualRate, to: gTargetRate)
    gSeg?.write(out)
    gWritten += out.count
}
closeSegment()
if let u = gUnit { AudioOutputUnitStop(u); AudioUnitUninitialize(u); AudioComponentInstanceDispose(u) }

log(String(format: "结束：callbacks=%d pulled=%d(%.1fs@%.0fk) written=%d(%.1fs@%.0fk) peak=%.4f renderErr=%d silenceFrames=%d duration=%.1fs",
        cb, sp, Double(sp) / gActualRate, gActualRate / 1000,
        gWritten, Double(gWritten) / gTargetRate, gTargetRate / 1000,
        pk, gRenderErrCount, gSilenceFlagFrames, Date().timeIntervalSince(gT0)))
log("WAV 输出目录：\(URL(fileURLWithPath: gOutDir).path)")
exit(0)
