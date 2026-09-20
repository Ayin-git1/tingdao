# macOS 原生麦克风模式与 Voice Processing 设计

## 目标

在不迁移 Python 录制、落盘、VAD 或转写逻辑的前提下，为 macOS 的麦克风录制提供 Apple 原生 Voice Processing 与官方“麦克风模式”系统选择 UI。模式仍由用户在 macOS UI 中选择，应用不使用私有 API，也不强制设置 Standard、Wide Spectrum 或 Voice Isolation。

## 现状与问题

Python 通过 `tingdao-mix` 的 stdout 接收 16 kHz、单声道、`s16le` PCM。普通 `AVAudioEngine` 输入 tap 的格式为单声道；启用 Voice Processing 后，输入节点输出格式变为多声道（本机为 9 声道）。直接读取第一个浮点通道会得到静音。此前仅提供后端接口，录制 UI 没有可调用入口。

## 架构

`tingdao-mix.swift` 保持为唯一 macOS 原生桥接进程。Python 继续负责进程生命周期、stdout PCM 读取、文件写入和转写。

```text
录制界面（仅麦克风）
  -> POST /api/microphone_modes
  -> Python 校验 macOS 12+ 与当前录制状态
  -> SIGUSR1 至正在录制的 tingdao-mix
  -> AVCaptureDevice.showSystemUserInterface(.microphoneModes)

tingdao-mix
  -> Voice Processing I/O 音频图
  -> 原生下混 / 重采样为 16 kHz 单声道 PCM
  -> stdout s16le
  -> Python 既有 raw.s16 / VAD / 转写管线
```

## Swift 音频图

仅 `mic` 和 `mix` 使用 Voice Processing。助手会建立实际渲染到静音输出的 Voice Processing I/O 图，避免扬声器回放。采样数据不得直接假设输入节点输出的第一个通道是语音。

Voice Processing 图固定为 `inputNode -> mainMixerNode -> outputNode`：连接格式为启用前的单声道输入格式，`mainMixerNode.outputVolume = 0`。启用 Voice Processing 后，tap 安装在 `mainMixerNode`，而非可能变为多声道的 `inputNode`；因此 tap 的格式保持为明确的单声道，再交给 `AVAudioConverter` 转为 16 kHz。Python 永远只接收既有的单声道 PCM 协议。

若 Voice Processing 无法启用、设备格式无法建立或原生图无法启动，助手记录精确错误并以普通单声道 AVAudioEngine 采集回退；录制不能因增强能力不可用而输出静音。

## Python 接口

- `is_microphone_modes_supported()`：仅 macOS 12 及以上返回真。
- `open_microphone_modes("mic")`：仅当前正在“仅麦克风”录制时向助手发送 `SIGUSR1`。
- `_spawn_sck()`：macOS 的 `mic` 与 `mix` 启动原生助手，传入 Voice Processing 请求；是否成功由助手日志和回退结果决定。

接口在非 macOS、低于 macOS 12、非仅麦克风模式、录制未启动或助手不可用时返回可读错误，不抛出未处理异常。

## 前端入口

录制底部控制区在停止按钮旁增加“麦克风模式…”按钮。它仅在 macOS 12+、当前录音来源为“仅麦克风”、且处于录制中时可见；点击调用 `/api/microphone_modes`。不可用时不显示该按钮，不显示任何 Standard/Wide Spectrum/Voice Isolation 的自定义选择器。

## 兼容性与权限

- `NSMicrophoneUsageDescription` 保持现有 Tauri `Info.plist` 声明。
- 麦克风权限继续由实际包内已签名助手请求；拒绝时使用既有中文错误。
- Voice Processing API 的最低版本是 macOS 10.15。
- 系统麦克风模式 UI 的最低版本是 macOS 12。
- macOS 10.15 至 11：可尝试 Voice Processing，但隐藏系统模式入口。

## 验证

1. 单元测试覆盖 macOS 版本门槛、仅麦克风状态限制与 SIGUSR1 分发。
2. Swift 编译必须无错误。
3. 已签名测试版助手以 `--mode mic --voice-processing` 启动时必须记录 `ready`，并产生非静音 PCM。
4. 使用系统麦克风说话时，输出音量与普通录制一致可用；Voice Processing 不可用时日志明确说明回退且仍有音频。
5. 在“仅麦克风”录制中点击入口能打开 macOS 官方麦克风模式 UI；其他模式没有可用入口。
