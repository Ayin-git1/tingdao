// tingdao-mix.swift — 听道 macOS 系统级音频采集助手（替代 BlackHole 虚拟声卡方案）
//
// 系统声音: ScreenCaptureKit（需屏幕录制权限；filter 必含一个显示器，视频压 2x2 占位）
// 麦克风:   AUVoiceProcessingIO（仅麦克风；Mic Modes 官方要求路径）/ AVAudioEngine（混录）
// 混音:     进程内实时相加(限幅)，输出 s16le/16kHz/单声道 —— 与原 ffmpeg avfoundation
//           的 stdout 协议逐字节一致，Python 侧 _read_loop/_finish 零改动。
//
// 用法: tingdao-mix --mode mic|mix|system --rate 16000
//   mode=mic     仅麦克风（AUVoiceProcessingIO，支持系统 Mic Modes）
//   mode=mix     系统声音 + 麦克风
//   mode=system  仅系统声音
// 麦克风模式: SIGUSR1 → 打开 macOS 系统麦克风模式面板（模式由用户选，程序不私设）
// 退出: SIGINT/SIGTERM 优雅停止（flush 后退出 0）
// 起动失败向 stderr 打中文原因并退出非 0（[sckmix] ready 打出后 Python 才认为就绪）
import Foundation
import AppKit
import ScreenCaptureKit
import CoreMedia
import CoreAudio
import AudioToolbox
import AVFoundation

// ---------- 线程安全 FIFO ----------
final class Fifo {
    private let cv = NSCondition()
    private var buf: [Float] = []
    func push(_ s: [Float]) {
        guard !s.isEmpty else { return }
        cv.lock(); buf.append(contentsOf: s); cv.signal(); cv.unlock()
    }
    /// 取 n 个样本，不足补零（时钟漂移的零头以静音填，不入正文）
    func pop(_ n: Int) -> [Float] {
        cv.lock(); defer { cv.unlock() }
        if buf.count >= n {
            let out = Array(buf[0..<n]); buf.removeFirst(n); return out
        }
        let out = buf + [Float](repeating: 0, count: n - buf.count)
        buf.removeAll(); return out
    }
    /// 只取当前已有帧，不补零；重采样器必须保留真实帧，避免回调抖动变成间歇性爆音。
    func take(_ n: Int) -> [Float] {
        cv.lock(); defer { cv.unlock() }
        let count = min(max(n, 0), buf.count)
        guard count > 0 else { return [] }
        let out = Array(buf[0..<count])
        buf.removeFirst(count)
        return out
    }
    /// 事件驱动消费者：等生产者实际推入 PCM，再只取已有帧；绝不补零。
    func waitTake(_ n: Int) -> [Float] {
        cv.lock(); defer { cv.unlock() }
        while buf.isEmpty && gStopFlag == 0 {
            cv.wait(until: Date(timeIntervalSinceNow: 0.25))
        }
        let count = min(max(n, 0), buf.count)
        guard count > 0 else { return [] }
        let out = Array(buf[0..<count])
        buf.removeFirst(count)
        return out
    }
    func wakeAll() { cv.lock(); cv.broadcast(); cv.unlock() }
    func drain() -> [Float] { cv.lock(); defer { cv.unlock() }; let o = buf; buf.removeAll(); return o }
    func depth() -> Int { cv.lock(); defer { cv.unlock() }; return buf.count }
}

/// VPIO 的单生产者/单消费者环形缓冲。实时回调只向这里写入原始帧；
/// 分配、重采样和文件 I/O 全留给消费者线程，满时丢弃最旧帧以保持实时性。
final class MicRingBuffer {
    private let cv = NSCondition()
    private var buf: [Float]
    private var readIndex = 0
    private var writeIndex = 0
    private var used = 0
    private(set) var dropped = 0

    init(capacity: Int) { buf = [Float](repeating: 0, count: capacity) }

    func writeMono(_ input: UnsafePointer<Float>, frames: Int, channels: Int,
                   nonInterleaved: Bool) {
        guard frames > 0 else { return }
        cv.lock()
        for frame in 0..<frames {
            if used == buf.count {
                readIndex = (readIndex + 1) % buf.count
                used -= 1
                dropped += 1
            }
            if channels == 1 || nonInterleaved {
                buf[writeIndex] = input[frame]
            } else {
                var sum: Float = 0
                for channel in 0..<channels { sum += input[frame * channels + channel] }
                buf[writeIndex] = sum / Float(channels)
            }
            writeIndex = (writeIndex + 1) % buf.count
            used += 1
        }
        cv.signal()
        cv.unlock()
    }

    /// 只返回已到达的真实帧；缓冲为空时等待，绝不补零。
    func waitRead(_ maxFrames: Int) -> [Float] {
        cv.lock()
        while used == 0 && gStopFlag == 0 {
            cv.wait(until: Date(timeIntervalSinceNow: 0.25))
        }
        let n = min(max(0, maxFrames), used)
        var out = [Float]()
        out.reserveCapacity(n)
        for _ in 0..<n {
            out.append(buf[readIndex])
            readIndex = (readIndex + 1) % buf.count
        }
        used -= n
        cv.unlock()
        return out
    }

    func wakeAll() { cv.lock(); cv.broadcast(); cv.unlock() }
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
var gMicRing = MicRingBuffer(capacity: 44100 * 8)

// ---------- AUVoiceProcessingIO 状态（Mic Modes 路径） ----------
// 依据 WWDC21 Session 10047: "In order to use Mic Modes, your app must adopt the
// Core Audio AUVoiceIO audio unit." —— AVCaptureSession 路径拿不到 Mic Modes 处理。
var gVpio: AudioComponentInstance?
var gVpioRate: Double = 0          // element1 实际客户端采样率（本机实测锁 44.1kHz）
var gVpioCh: Int = 1
var gVpioNonInterleaved = false
var gVpioCbCount = 0
var gVpioPulled = 0
var gVpioPeak: Float = 0
var gVpioRenderErr: OSStatus = 0
var gVpioRenderErrCount = 0
var gVpioRenderList: UnsafeMutablePointer<AudioBufferList>?
var gVpioRenderListRaw: UnsafeMutableRawPointer?
var gVpioRenderData: UnsafeMutableRawPointer?
var gVpioRenderFrames = 0
// 真人验收中爆点恰好落在 512 帧回调边界；记录源 PCM 边界是否已经断裂，
// 以区分采集端问题和后续重采样/落盘问题。
var gVpioLastSample: Float?
var gVpioBoundaryMaxStep: Float = 0
var gVpioBoundaryStepCount = 0
var gMicFifoRate: Double = 0        // gMicFifo 里样本的实际采样率
// 泵侧健康度：writeS16 被下游阻塞 = 丢拍 = 音频出现 20ms 的洞（听感就是一卡一卡/颗粒）
var gPumpTicks = 0
var gPumpSlow = 0
var gPumpBlockedMs = 0.0
var gPumpBytes = 0
var gMicWriterDone: DispatchSemaphore?
var gOut: FileHandle = .standardOutput
let gOutLK = NSLock()
var gMode = "mix"
var gRate = 16000
var gMicName = ""
var gFifoPath = ""                 // --fifo：PCM 改写进命名管道（以 .app 身份被 open 拉起时 stdout 不可用）
var gPidFile = ""                  // --pidfile：回报 pid，供 Python 发 SIGINT/SIGUSR1
var gMasterPath = ""               // --master：仅麦克风的原始采样率 s16le 母带
var gMasterRateFile = ""           // --master-rate-file：回报实际 VPIO 采样率
var gMasterOut: FileHandle?
var gShowMicModes: Int32 = 0

func log(_ s: String) { fputs("[sckmix] \(s)\n", stderr) }
func fail(_ s: String, _ code: Int32) -> Never { log(s); exit(code) }

func writeS16(_ samples: [Float]) {
    var out = [Int16](repeating: 0, count: samples.count)
    for (i, v) in samples.enumerated() {
        let c = max(-1.0, min(1.0, v))
        out[i] = Int16(c * 32767.0)
    }
    out.withUnsafeBytes { raw in
        let t0 = DispatchTime.now()
        gOutLK.lock(); gOut.write(Data(raw)); gOutLK.unlock()
        let ms = Double(DispatchTime.now().uptimeNanoseconds - t0.uptimeNanoseconds) / 1_000_000.0
        gPumpBytes += raw.count
        if ms > 15 { gPumpSlow += 1; gPumpBlockedMs += ms }   // 一拍只有 20ms, 写超过 15ms 就是被下游堵住了
    }
}

/// 只由仅麦克风的写盘线程调用；VPIO 回调绝不触及文件句柄。
func writeMasterS16(_ samples: [Float]) {
    guard let master = gMasterOut, !samples.isEmpty else { return }
    var out = [Int16](repeating: 0, count: samples.count)
    for (i, v) in samples.enumerated() {
        out[i] = Int16(max(-1.0, min(1.0, v)) * 32767.0)
    }
    out.withUnsafeBytes { master.write(Data($0)) }
}

func openMasterOutput() {
    guard !gMasterPath.isEmpty else { return }
    FileManager.default.createFile(atPath: gMasterPath, contents: nil)
    guard let out = FileHandle(forWritingAtPath: gMasterPath) else {
        fail("无法创建高保真录音母带 \(gMasterPath)", 7)
    }
    gMasterOut = out
}

/// 系统声和麦克风相加后先按本拍峰值留余量，再转成 s16；
/// 不能把超 1.0 的和直接交给 writeS16 硬截断，否则会产生明显削波滋声。
func mixWithHeadroom(_ a: [Float], _ b: [Float]) -> [Float] {
    let n = min(a.count, b.count)
    guard n > 0 else { return [] }
    var mixed = [Float](repeating: 0, count: n)
    var peak: Float = 0
    for i in 0..<n {
        let v = a[i] + b[i]
        mixed[i] = v
        let av = v < 0 ? -v : v
        if av > peak { peak = av }
    }
    let gain: Float = peak > 0.95 ? 0.95 / peak : 1.0
    if gain < 1.0 {
        for i in 0..<n { mixed[i] *= gain }
    }
    return mixed
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

func startEngineMic(_ micName: String) {
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
    gMicFifoRate = Double(gRate)     // 这条路已在回调里转好 gRate, 泵不再二次重采样
    log("mic ok sr=\(inFmt.sampleRate) ch=\(inFmt.channelCount)")
}

// ---------- 重采样：VPIO 原生率(实测 44.1kHz) → 管线要的 gRate ----------
// 实测(macOS 27)：给 VPIO element1 预设 16k/48k/stereo/Int16 任一格式,
// AudioUnitInitialize 一律失败 -10875(kAudioUnitErr_FailedInitialization)。
// 且【不能】用朴素线性插值降采样：无抗混叠低通, 实测 15kHz 音会折进 1kHz 且保留 33% 幅度
// —— 听感就是毛刺/颗粒。改用 AVAudioConverter(带滤波), 并放在泵线程做, 不占实时音频线程。
var gMicInFmt: AVAudioFormat?
var gMicOutFmt: AVAudioFormat?
var gMicConv: AVAudioConverter?
var gMicCarry = [Float]()           // 已转换、尚未被本拍消费的 gRate 样本

func setupMicResample(from inRate: Double) {
    gMicFifoRate = inRate
    guard abs(inRate - Double(gRate)) > 0.5 else { gMicConv = nil; return }
    guard let inf = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: inRate,
                                  channels: 1, interleaved: false),
          let outf = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(gRate),
                                   channels: 1, interleaved: false),
          let conv = AVAudioConverter(from: inf, to: outf) else {
        log("重采样器创建失败，退回线性插值")
        return
    }
    // AVAudioConverter 默认就是带限插值(自带抗混叠低通), 无需额外设置算法
    gMicInFmt = inf; gMicOutFmt = outf; gMicConv = conv
    log("重采样 \(Int(inRate))→\(gRate)Hz 已就绪(AVAudioConverter)")
}

/// 降级用线性插值（仅当 AVAudioConverter 创建失败时用；有混叠但不至于把音频变速）
var gLinPos = 0.0
func linearFallback(_ n: Int) -> [Float] {
    let ratio = gMicFifoRate / Double(gRate)
    var out: [Float] = []
    while out.count < n {
        let need = Int(gLinPos) + 2 - gLinBuf.count
        if need > 0 { gLinBuf.append(contentsOf: gMicFifo.take(max(320, need))) }
        let idx = Int(gLinPos)
        if idx + 1 >= gLinBuf.count { break }
        let fr = Float(gLinPos - Double(idx))
        out.append(gLinBuf[idx] + (gLinBuf[idx + 1] - gLinBuf[idx]) * fr)
        gLinPos += ratio
    }
    let drop = Int(gLinPos)
    if drop > 0 { gLinBuf.removeFirst(min(drop, gLinBuf.count)); gLinPos -= Double(drop) }
    return out.count < n ? out + [Float](repeating: 0, count: n - out.count) : out
}
var gLinBuf = [Float]()

/// 从 gMicFifo 取 n 个 gRate 样本（不足补零，保持泵的定拍语义）
func popMic(_ n: Int) -> [Float] {
    if gMicConv == nil {
        return abs(gMicFifoRate - Double(gRate)) < 0.5 ? gMicFifo.pop(n) : linearFallback(n)
    }
    let ratio = gMicFifoRate / Double(gRate)
    // 只取已有帧，不能让 pop() 补零后丢掉真实帧；输出端最后再按固定节拍补齐。
    // 改用「迭代上限 + 无进展」双保险，避免转换器稍有延迟就空转。
    var spins = 0
    while gMicCarry.count < n && spins < 8 {
        spins += 1
        let before = gMicCarry.count
        let want = Int(Double(n - gMicCarry.count) * ratio) + 128
        let src = gMicFifo.take(want)
        if src.isEmpty { break }
        guard let conv = gMicConv, let inf = gMicInFmt, let outf = gMicOutFmt,
              let inBuf = AVAudioPCMBuffer(pcmFormat: inf, frameCapacity: AVAudioFrameCount(src.count)),
              let outBuf = AVAudioPCMBuffer(pcmFormat: outf, frameCapacity: AVAudioFrameCount(src.count) + 128)
        else { break }
        inBuf.frameLength = AVAudioFrameCount(src.count)
        memcpy(inBuf.floatChannelData![0], src, src.count * MemoryLayout<Float>.size)
        var fed = false
        var err: NSError?
        _ = conv.convert(to: outBuf, error: &err) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true; status.pointee = .haveData; return inBuf
        }
        // 输入回调用 noDataNow 收尾时，转换器通常回 .inputRanDry；它仍可能已经
        // 产出有效帧。帧数才是唯一能决定要不要消费的依据，不能按状态丢掉它。
        if outBuf.frameLength > 0, let ch = outBuf.floatChannelData?[0] {
            gMicCarry.append(contentsOf: Array(UnsafeBufferPointer(start: ch, count: Int(outBuf.frameLength))))
        }
        if gMicCarry.count == before { break }       // 转换器没吐东西，别再空转
    }
    return gMicFifoTakePadded(n)
}

func gMicFifoTakePadded(_ n: Int) -> [Float] {
    let take = min(n, gMicCarry.count)
    let out = Array(gMicCarry[0..<take])
    gMicCarry.removeFirst(take)
    return out.count < n ? out + [Float](repeating: 0, count: n - out.count) : out
}

/// 仅麦克录制的回调→写盘转换：输入块到达才执行，输出帧数由转换器实际给出。
/// 这里没有节拍器、没有补零；落盘样本数就是录音时钟的唯一来源。
func resampleMicBlock(_ src: [Float]) -> [Float] {
    guard !src.isEmpty else { return [] }
    guard let conv = gMicConv, let inf = gMicInFmt, let outf = gMicOutFmt else { return src }
    let cap = AVAudioFrameCount(Double(src.count) * Double(gRate) / gMicFifoRate + 256)
    guard let inBuf = AVAudioPCMBuffer(pcmFormat: inf, frameCapacity: AVAudioFrameCount(src.count)),
          let outBuf = AVAudioPCMBuffer(pcmFormat: outf, frameCapacity: cap) else { return [] }
    inBuf.frameLength = AVAudioFrameCount(src.count)
    memcpy(inBuf.floatChannelData![0], src, src.count * MemoryLayout<Float>.size)
    var fed = false
    var err: NSError?
    _ = conv.convert(to: outBuf, error: &err) { _, status in
        if fed { status.pointee = .noDataNow; return nil }
        fed = true; status.pointee = .haveData; return inBuf
    }
    guard outBuf.frameLength > 0, let ch = outBuf.floatChannelData?[0] else { return [] }
    return Array(UnsafeBufferPointer(start: ch, count: Int(outBuf.frameLength)))
}

/// 在启动 VPIO 后一次性分配 render buffer；实时回调只能复用这些内存。
func prepareVpioRenderBuffers(_ unit: AudioComponentInstance) {
    var maxFrames: UInt32 = 4096
    var size = UInt32(MemoryLayout<UInt32>.size)
    _ = AudioUnitGetProperty(unit, kAudioUnitProperty_MaximumFramesPerSlice,
                             kAudioUnitScope_Global, 0, &maxFrames, &size)
    let frames = max(1, Int(maxFrames))
    let channels = max(1, gVpioCh)
    let listRaw = UnsafeMutableRawPointer.allocate(
        byteCount: MemoryLayout<AudioBufferList>.size + (channels - 1) * MemoryLayout<AudioBuffer>.size,
        alignment: 8)
    let dataRaw = UnsafeMutableRawPointer.allocate(
        byteCount: frames * MemoryLayout<Float>.size * (gVpioNonInterleaved ? channels : channels),
        alignment: 16)
    let list = listRaw.assumingMemoryBound(to: AudioBufferList.self)
    list.pointee.mNumberBuffers = UInt32(gVpioNonInterleaved ? channels : 1)
    let bufferBase = listRaw + (MemoryLayout.offset(of: \AudioBufferList.mBuffers) ?? 16)
    if gVpioNonInterleaved {
        for channel in 0..<channels {
            let buffer = (bufferBase + channel * MemoryLayout<AudioBuffer>.size)
                .assumingMemoryBound(to: AudioBuffer.self)
            buffer.pointee.mNumberChannels = 1
            buffer.pointee.mDataByteSize = UInt32(frames * MemoryLayout<Float>.size)
            buffer.pointee.mData = dataRaw + channel * frames * MemoryLayout<Float>.size
        }
    } else {
        list.pointee.mBuffers.mNumberChannels = UInt32(channels)
        list.pointee.mBuffers.mDataByteSize = UInt32(frames * channels * MemoryLayout<Float>.size)
        list.pointee.mBuffers.mData = dataRaw
    }
    gVpioRenderListRaw = listRaw
    gVpioRenderList = list
    gVpioRenderData = dataRaw
    gVpioRenderFrames = frames
}

func releaseVpioRenderBuffers() {
    gVpioRenderListRaw?.deallocate()
    gVpioRenderData?.deallocate()
    gVpioRenderListRaw = nil
    gVpioRenderList = nil
    gVpioRenderData = nil
    gVpioRenderFrames = 0
}

/// AudioUnitRender 会把 mDataByteSize 改为本次实际写入长度；下一次拉取前恢复容量。
/// 这只改预分配 ABL 的元数据，不分配内存，也不复制 PCM。
func resetVpioRenderByteSizes(_ frames: Int) {
    guard let list = gVpioRenderList else { return }
    let count = Int(list.pointee.mNumberBuffers)
    let base = UnsafeMutableRawPointer(list) + (MemoryLayout.offset(of: \AudioBufferList.mBuffers) ?? 16)
    let buffers = base.assumingMemoryBound(to: AudioBuffer.self)
    let bytesPerBuffer = frames * MemoryLayout<Float>.size *
        (gVpioNonInterleaved ? 1 : max(1, gVpioCh))
    for index in 0..<count {
        buffers[index].mDataByteSize = UInt32(bytesPerBuffer)
    }
}

// ---------- VPIO 输入/输出回调 ----------
// VPIO 的硬件输入走 element 1 的 input callback；在这里拉取并连续写环形缓冲。
// 输出 element 0 只填静音，两者不能复用同一个回调，否则输入时间线会被输出拉取扰乱。
let vpioInputRender: AURenderCallback = { _, _, inTimeStamp, inBusNumber, inNumberFrames, _ in
    guard inBusNumber == 1 else { return noErr }

    // 拉取麦克风 PCM。
    guard let unit = gVpio, inNumberFrames > 0 else { return noErr }
    let frames = Int(inNumberFrames)
    guard frames <= gVpioRenderFrames, let listP = gVpioRenderList,
          let dataRaw = gVpioRenderData else { return noErr }
    resetVpioRenderByteSizes(frames)
    var flags = AudioUnitRenderActionFlags(rawValue: 0)
    let st = AudioUnitRender(unit, &flags, inTimeStamp, inBusNumber, inNumberFrames, listP)
    if st != noErr {                       // 单次拉取失败不拖垮整条链路，计数后继续
        gVpioRenderErr = st
        gVpioRenderErrCount += 1
        return noErr
    }

    // 回调只把输入连续写入环形缓冲；重采样/写盘由独立消费者线程完成。
    let f = dataRaw.assumingMemoryBound(to: Float.self)
    gVpioCbCount += 1
    gVpioPulled += frames
    gMicRing.writeMono(f, frames: frames, channels: gVpioCh, nonInterleaved: gVpioNonInterleaved)
    return noErr
}

let vpioOutputSilence: AURenderCallback = { _, _, _, inBusNumber, _, ioData in
    guard inBusNumber == 0, let ioData else { return noErr }

    // 输出端静音（本助手只采不播；录制期间用户正常听自己的扬声器，不受影响）。
    let outN = Int(ioData.pointee.mNumberBuffers)
    if outN > 0 {
        let base = UnsafeMutableRawPointer(ioData) + (MemoryLayout.offset(of: \AudioBufferList.mBuffers) ?? 16)
        let bufs = base.assumingMemoryBound(to: AudioBuffer.self)
        for k in 0..<outN {
            if let d = bufs[k].mData, bufs[k].mDataByteSize > 0 {
                memset(d, 0, Int(bufs[k].mDataByteSize))
            }
        }
    }
    return noErr
}

func microphoneModeName() -> String {
    guard #available(macOS 12.0, *) else { return "unsupported" }
    switch AVCaptureDevice.activeMicrophoneMode {
    case .standard: return "standard"
    case .wideSpectrum: return "wideSpectrum"
    case .voiceIsolation: return "voiceIsolation"
    @unknown default: return "unknown"
    }
}

/// 用户选的模式（sticky per app）；active 才是当前真正生效的（受音频路由影响）
func microphonePreferredName() -> String {
    guard #available(macOS 12.0, *) else { return "unsupported" }
    switch AVCaptureDevice.preferredMicrophoneMode {
    case .standard: return "standard"
    case .wideSpectrum: return "wideSpectrum"
    case .voiceIsolation: return "voiceIsolation"
    @unknown default: return "unknown"
    }
}

/// 默认输入设备名（CoreAudio 层，实际被占用的物理设备以它为准）
func defaultInputDeviceName() -> String {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var id: AudioDeviceID = 0
    var sz = UInt32(MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
            &addr, 0, nil, &sz, &id) == noErr, id != 0 else { return "?" }
    var naddr = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName,
            mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var name: CFString?
    var ns = UInt32(MemoryLayout<CFString?>.size)
    let ok = withUnsafeMutablePointer(to: &name) { p in
        AudioObjectGetPropertyData(id, &naddr, 0, nil, &ns, p)
    }
    return ok == noErr ? (name as String? ?? "?") : "?"
}

/// 自证横幅：把「谁在占用麦克风、它有没有 App 身份」写成日志证据
func diagBanner() {
    let bid = Bundle.main.bundleIdentifier ?? "无(裸可执行文件)"
    let bpath = Bundle.main.bundlePath
    var avName = "无"
    if #available(macOS 10.14, *) { avName = AVCaptureDevice.default(for: .audio)?.localizedName ?? "无" }
    log("diag 进程 pid=\(getpid()) ppid=\(getppid()) 名=\(ProcessInfo.processInfo.processName)")
    log("diag 本进程 bundle id=\(bid) path=\(bpath)")
    log("diag 设备 CoreAudio默认输入=\(defaultInputDeviceName()) AVFoundation默认=\(avName)")
    log("diag 模式 preferred=\(microphonePreferredName()) active=\(microphoneModeName())")
    log("diag 前台判定 activeApp=\(NSWorkspace.shared.frontmostApplication?.localizedName ?? "?")（与面板能否弹出无关，已实测）")
}

func startVpioMic(_ micName: String) {
    var desc = AudioComponentDescription(
        componentType: kAudioUnitType_Output,
        componentSubType: kAudioUnitSubType_VoiceProcessingIO,
        componentManufacturer: kAudioUnitManufacturer_Apple,
        componentFlags: 0, componentFlagsMask: 0)
    guard let comp = AudioComponentFindNext(nil, &desc) else {
        fail("本机没有 AUVoiceProcessingIO 组件（Mic Modes 需要 macOS 12+ 且 2018 年后的机型）", 5)
    }
    var unit: AudioComponentInstance?
    var st = AudioComponentInstanceNew(comp, &unit)
    guard st == noErr, let u = unit else { fail("创建 AUVoiceProcessingIO 实例失败 (\(st))", 5) }
    gVpio = u

    // element 1(输入)默认关闭，必须启用；element 0(输出)保持默认开启，靠它驱动拉取节奏
    var on: UInt32 = 1
    st = AudioUnitSetProperty(u, kAudioOutputUnitProperty_EnableIO,
            kAudioUnitScope_Input, 1, &on, 4)
    guard st == noErr else { fail("启用麦克风输入 IO 失败 (\(st))", 5) }

    // 设置里指定的麦克风按名字子串匹配；VPIO 对非默认设备的支持有限，失败如实打日志并回落默认
    if !micName.isEmpty {
        let devs = inputDeviceList()
        if let d = devs.first(where: { $0.name.lowercased().contains(micName.lowercased()) }) {
            var did = d.id
            st = AudioUnitSetProperty(u, kAudioOutputUnitProperty_CurrentDevice,
                    kAudioUnitScope_Input, 1, &did, UInt32(MemoryLayout<AudioDeviceID>.size))
            log(st == noErr ? "mic device → \(d.name)" : "指定麦克风失败(\(st))，用默认输入")
        } else {
            log("找不到名为「\(micName)」的输入设备，用默认输入")
        }
    }

    var inputCallback = AURenderCallbackStruct(inputProc: vpioInputRender, inputProcRefCon: nil)
    st = AudioUnitSetProperty(u, kAudioOutputUnitProperty_SetInputCallback,
            kAudioUnitScope_Global, 1, &inputCallback,
            UInt32(MemoryLayout<AURenderCallbackStruct>.size))
    guard st == noErr else { fail("挂麦克风输入回调失败 (\(st))", 5) }
    var outputCallback = AURenderCallbackStruct(inputProc: vpioOutputSilence, inputProcRefCon: nil)
    st = AudioUnitSetProperty(u, kAudioUnitProperty_SetRenderCallback,
            kAudioUnitScope_Global, 0, &outputCallback,
            UInt32(MemoryLayout<AURenderCallbackStruct>.size))
    guard st == noErr else { fail("挂麦克风输出回调失败 (\(st))", 5) }

    // 母带必须保留真实电平；关闭 VPIO 默认的自动增益，避免把底噪和爆点一起抬高。
    var agcEnabled: UInt32 = 0
    st = AudioUnitSetProperty(u, kAUVoiceIOProperty_VoiceProcessingEnableAGC,
            kAudioUnitScope_Global, 1, &agcEnabled, UInt32(MemoryLayout<UInt32>.size))
    guard st == noErr else { fail("关闭麦克风自动增益失败 (\(st))", 5) }

    st = AudioUnitInitialize(u)
    guard st == noErr else { fail("AUVoiceProcessingIO 初始化失败 (\(st))", 5) }

    var got = AudioStreamBasicDescription()
    var sz = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    if AudioUnitGetProperty(u, kAudioUnitProperty_StreamFormat,
            kAudioUnitScope_Output, 1, &got, &sz) == noErr {
        gVpioRate = got.mSampleRate
        gVpioCh = max(1, Int(got.mChannelsPerFrame))
        gVpioNonInterleaved = (got.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0
    }
    guard gVpioRate > 0 else { fail("读不到麦克风输入格式", 5) }
    setupMicResample(from: gVpioRate)
    prepareVpioRenderBuffers(u)
    if !gMasterRateFile.isEmpty {
        do {
            try "\(Int(gVpioRate))\n".write(toFile: gMasterRateFile, atomically: true, encoding: .utf8)
        } catch {
            fail("无法写入高保真母带采样率", 7)
        }
    }

    st = AudioOutputUnitStart(u)
    guard st == noErr else { fail("麦克风启动失败 (\(st))（检查麦克风权限）", 5) }
    log("vpio ok sr=\(Int(gVpioRate)) ch=\(gVpioCh) pipe=\(gRate)Hz preferred=\(microphonePreferredName()) active=\(microphoneModeName())")
}

// ---------- 仅麦克：事件驱动写盘 ----------
func startMicWriter() {
    let done = DispatchSemaphore(value: 0)
    gMicWriterDone = done
    Thread.detachNewThread {
        defer { done.signal() }
        while gStopFlag == 0 {
            let src = gMicRing.waitRead(4096)
            if !src.isEmpty {
                writeMasterS16(src)
                writeS16(resampleMicBlock(src))
            }
        }
        // VPIO 已停后，排空真实剩余帧；不为了凑整补任何静音。
        while true {
            let src = gMicRing.waitRead(4096)
            guard !src.isEmpty else { break }
            writeMasterS16(src)
            writeS16(resampleMicBlock(src))
        }
    }
}

// ---------- 混音/系统声泵: 专用线程 + 绝对时刻追赶 ----------
// 不用 DispatchSourceTimer：助手现在是 LaunchServices 拉起的后台 App，macOS 会对
// 「无前台窗口的 App」做定时器合并(coalescing)，20ms 节拍被拖成几十毫秒 →
// 实测落盘只有实时的 48%、界面时钟半速。专用线程按绝对时刻排拍，不受合并影响。
func startPump() {
    if gMode == "mic" { startMicWriter(); return }
    let tick = 320                      // 20ms @16k
    Thread.detachNewThread {
        let t0 = Date()
        var n = 0
        while gStopFlag == 0 {
            n += 1
            gPumpTicks += 1
            var mix: [Float]
            switch gMode {
            case "system":
                mix = gSys!.fifo.pop(tick)
            case "mix":
                let a = gSys!.fifo.pop(tick)
                let b = popMic(tick)
                mix = mixWithHeadroom(a, b)
            default:
                mix = popMic(tick)
            }
            writeS16(mix)
            let dt = t0.addingTimeInterval(Double(n) * 0.02).timeIntervalSinceNow
            if dt > 0 {
                Thread.sleep(forTimeInterval: dt)
            } else if dt < -0.5 {
                // 落后超过半秒(下游长时间堵死): 重新对齐而不是疯狂补拍，并如实报积压
                log(String(format: "⚠ 泵落后 %.0fms，重排节拍；当前积压=%d", -dt * 1000.0, gMicFifo.depth()))
                n = Int(Date().timeIntervalSince(t0) / 0.02)
            }
        }
    }
}

func flushAndExit() -> Never {
    if let v = gVpio {
        log("vpio callbacks=\(gVpioCbCount) pulled=\(gVpioPulled) peak=\(String(format: "%.4f", gVpioPeak)) renderErr=\(gVpioRenderErrCount)(last=\(gVpioRenderErr)) boundaryMaxStep=\(String(format: "%.4f", gVpioBoundaryMaxStep)) boundaryStepCount=\(gVpioBoundaryStepCount)")
        AudioOutputUnitStop(v)
        AudioUnitUninitialize(v)
        AudioComponentInstanceDispose(v)
        releaseVpioRenderBuffers()
        gVpio = nil
    }
    if gMode == "mic" {
        gMicRing.wakeAll()
        _ = gMicWriterDone?.wait()
        try? gMasterOut?.close()
        gMasterOut = nil
    }
    // 停止前把两路残余一次性混完（长度不齐补零）
    let sys = gSys?.fifo.drain() ?? []
    var mic: [Float] = []
    if gMode == "mix" {
        // 走 VPIO 时 gMicFifo 里是原生率样本, 必须经 popMic 转换后再收尾, 不能直接 drain
        for _ in 0..<10 {
            if gMicFifo.depth() == 0 && gMicCarry.isEmpty { break }
            mic.append(contentsOf: popMic(320))
        }
    }
    let n = max(sys.count, mic.count)
    if n > 0 {
        var mix = [Float](repeating: 0, count: n)
        if gMode == "mix" {
            for i in 0..<n { mix[i] = (i < sys.count ? sys[i] : 0) + (i < mic.count ? mic[i] : 0) }
        } else if gMode == "mic" {
            for i in 0..<n { mix[i] = mic[i] }
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
func sigHandler(_ s: Int32) {
    if s == SIGUSR1 { gShowMicModes = 1 } else { gStopFlag = 1 }
}

func installSignals() {
    signal(SIGINT, sigHandler)
    signal(SIGTERM, sigHandler)
    signal(SIGUSR1, sigHandler)
}

/// AppKit 引导：showSystemUserInterface 要求进程与窗口服务器建立 App 连接，
/// 纯命令行裸进程不初始化 NSApplication 时该 API 静默无效（实测：不弹面板）。
/// 用 .accessory 策略：建立连接但不出现在 Dock、不抢焦点。
func bootstrapAppKit() {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    log("AppKit 已引导 policy=accessory bundle=\(Bundle.main.bundleIdentifier ?? "无")")
}

func showMicrophoneModes() {
    if #available(macOS 12.0, *) {
        // TingdaoMic 是 accessory App；先显式激活它，系统的深链 UI 才不会被
        // 当前前台应用吞掉。调用本身仍是 Apple 原生 Mic Modes 面板。
        NSApplication.shared.activate(ignoringOtherApps: true)
        log("收到菜单请求 → 打开系统麦克风模式面板（当前 active=\(microphoneModeName())）")
        AVCaptureDevice.showSystemUserInterface(.microphoneModes)
    } else {
        log("麦克风模式需要 macOS 12 或更高版本")
    }
}

// ---------- main ----------
let args = CommandLine.arguments
var i = 1
while i < args.count {
    switch args[i] {
    case "--mode": i += 1; gMode = i < args.count ? args[i] : "mix"
    case "--rate": i += 1; gRate = i < args.count ? Int(args[i]) ?? 16000 : 16000
    case "--mic":  i += 1; gMicName = i < args.count ? args[i] : ""
    case "--fifo": i += 1; gFifoPath = i < args.count ? args[i] : ""
    case "--pidfile": i += 1; gPidFile = i < args.count ? args[i] : ""
    case "--master": i += 1; gMasterPath = i < args.count ? args[i] : ""
    case "--master-rate-file": i += 1; gMasterRateFile = i < args.count ? args[i] : ""
    case "--log":
        i += 1
        if i < args.count {
            // 以 .app 身份被 LaunchServices 拉起时 stderr 会进黑洞，--log 把它落到文件
            let fd = open(args[i], O_WRONLY | O_CREAT | O_APPEND, 0o644)
            if fd >= 0 { dup2(fd, STDERR_FILENO); close(fd) }
        }
    default: break
    }
    i += 1
}
guard gMode == "mix" || gMode == "system" || gMode == "mic" else { fail("未知模式 \(gMode)", 2) }
guard gRate > 4000 && gRate <= 96000 else { fail("非法采样率 \(gRate)", 2) }

// 以 .app 身份被 open 拉起时：先回报 pid，再把 PCM 出口切到命名管道。
// 打开写端会阻塞到 Python 打开读端 —— 顺序不能反，否则 Python 拿不到 pid 就没法停它。
if !gPidFile.isEmpty {
    try? String(getpid()).write(toFile: gPidFile, atomically: true, encoding: .utf8)
}
if !gFifoPath.isEmpty {
    let fd = open(gFifoPath, O_WRONLY)
    if fd < 0 { fail("打不开音频管道 \(gFifoPath)（errno=\(errno)）", 7) }
    gOut = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
    log("PCM 出口已切到管道 \(gFifoPath)")
}
if gMode == "mic" { openMasterOutput() }

// 1. SCK 起流（仅系统声/混录；仅麦克风不需要屏幕录制权限）
if gMode != "mic" {
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
}

// 2. 仅麦克风由 VPIO 持续写环形缓冲，消费者线程独立重采样和写盘。
if gMode == "mic" { bootstrapAppKit(); startVpioMic(gMicName); diagBanner() }
if gMode == "mix" { startEngineMic(gMicName) }

// 3. 信号 + 混音泵, 主线程挂起等待 gStop
installSignals()
startPump()
log("ready")
func runMainLoop() -> Never {
    var lastMicMode = gMode == "mic" ? microphoneModeName() : ""
    var lastBeat = Date()
    let pumpT0 = Date()
    while gStopFlag == 0 {
        if gShowMicModes != 0 {
            gShowMicModes = 0
            showMicrophoneModes()
        }
        // 录制中实时侦测用户在系统面板里的切换：active 才是真正生效的那一个
        if gMode == "mic" {
            let m = microphoneModeName()
            if m != lastMicMode {
                log("麦克风模式变化：\(lastMicMode) → \(m)（preferred=\(microphonePreferredName())）")
                lastMicMode = m
            }
        }
        // 每 5 秒一次健康心跳：pulled 与 written 的差 + 被堵拍次数, 丢帧一眼可见
        if Date().timeIntervalSince(lastBeat) >= 5.0 {
            lastBeat = Date()
            let inRate = gVpioRate > 0 ? gVpioRate : 44100
            log(String(format: "健康 wall=%.1fs pulled=%.1fs written=%.1fs 堵拍=%d(共%.0fms) 积压=%d boundaryMaxStep=%.4f boundaryStepCount=%d",
                       Date().timeIntervalSince(pumpT0), Double(gVpioPulled) / inRate,
                       Double(gPumpBytes) / 2.0 / Double(gRate),
                       gPumpSlow, gPumpBlockedMs, gMicFifo.depth(),
                       gVpioBoundaryMaxStep, gVpioBoundaryStepCount))
        }
        // showSystemUserInterface 是非阻塞 API；主线程必须持续跑 AppKit RunLoop，
        // 否则请求虽已记录，系统面板不会真正派发出来。
        RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.1))
    }
    flushAndExit()
}
runMainLoop()
