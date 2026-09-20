# 高保真麦克风母带设计

## 目标

仅麦克风录制保留 VPIO 实际输入采样率的单声道无损母带，同时继续向既有实时 VAD、转写和时间线提供 16 kHz PCM。默认回放使用高保真母带；可选试听降噪副本不得覆盖母带。

## 约束

- VPIO 回调只连续写入环形缓冲，不能执行重采样或文件 I/O。
- VPIO 输入格式以运行时读取的 `gVpioRate` 为准；当前 MacBook Pro 为 44.1 kHz。
- 16 kHz 流仍是实时识别、VAD 和既有 `raw.s16` 的唯一格式。
- 仅影响 macOS 的 `mic` 模式；`mix`、`system`、Windows 和正式安装版不改变。
- 测试版继续从源码目录的 `TingdaoMic.app` 启动已签名助手。

## 数据流

`AUVoiceProcessingIO → MicRingBuffer → 独立写入线程`

写入线程对每批真实原始帧执行两项工作：第一，将 44.1 kHz 单声道 s16le 追加到 Python 传入的 `raw-master.s16`；第二，使用现有 `AVAudioConverter` 下采样为 16 kHz，再通过现有 FIFO/stdout 交给 Python。两项均不补零。停止时先停 VPIO，再排空环形缓冲，最后关闭两个出口。

Python 仍把 stdout 的 16 kHz 数据写入 `raw.s16` 并供实时转写。收尾时若存在有效的 `raw-master.s16`，只将它编码为默认回放用的 `audio.wav`，并以实际输入采样率标注 `audioMaster`；`audio.m4a` 继续由 16 kHz 的 `raw.s16` 生成，供既有离线转写链路使用。临时双份 raw 在收尾与删除音频时都必须清理。

## 验收

- 新 `audio.wav` 的采样率与 VPIO 实际输入匹配（当前为 44.1 kHz），默认回放指向它。
- 实时识别仍只接收 16 kHz、单声道 PCM。
- VPIO 回调不包含重采样、文件写入或零填充。
- VPIO、转写流和母带收尾均通过测试；测试助手保持 arm64 / macOS 26.0 且签名有效。
