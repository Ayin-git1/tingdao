# 第三方组件与许可说明 (Third-Party Notices)

本程序（听道）**只发布程序本体**：不打包任何第三方库、命令行工具、虚拟声卡驱动或模型。
用户需自行安装依赖、自行下载模型。下列条目仅为**致谢与义务提示**——你在使用/分发
由这些组件支撑的功能时，须各自遵守其上游许可证。本程序自身的许可见仓库根目录的
`LICENSE`（PolyForm Noncommercial License 1.0.0，仅供个人非商业使用）。

> ⚠ 下表许可证以我掌握的信息填写，标注了把握程度。公开仓库前，请逐条以各官方仓库/模型页为准复核
> （尤其打「待核对」的）。因为我们不再分发这些组件，核对主要是为了正确致谢、避免误导。

## Python 库（用户 `pip install -r requirements.txt` 自行安装）

| 组件 | 用途 | 许可证 | 来源 |
|---|---|---|---|
| numpy | 数值/音频处理 | BSD-3-Clause | numpy/numpy |
| requests | HTTP（云端接口） | Apache-2.0 | psf/requests |
| sherpa-onnx | SenseVoice 实时识别 + Silero VAD 断句 | Apache-2.0 | k2-fsa/sherpa-onnx |
| pywebview | 原生窗口（WKWebView） | 待核对（BSD/MIT） | r0xr/pywebview（r0y8? 以官方为准） |
| pyobjc | macOS Cocoa 绑定 | 待核对（MIT + 部分 LGPL） | relmpl/pyobjc |
| mlx | Apple Silicon 计算框架 | MIT | ml-explore/mlx |
| mlx-whisper | 本地 Whisper 精修（MLX 版） | MIT | princecanavin/mlx-whisper |

## 命令行工具与驱动（用户自行安装）

| 组件 | 用途 | 许可证 |
|---|---|---|
| FFmpeg | 采集/解码/抽轨/预处理 | LGPL/GPL（视构建选项而定） |
| switchaudio-osx | 录制前后切换默认输出设备 | 待核对（多为 MIT） |
| BlackHole | 系统声音内录的虚拟声卡（mac） | 待核对（GPL 系列）——需管理员安装 |

## 模型（用户自行下载，在「设置 → 本地模型」填路径）

| 模型 | 用途 | 许可提示 |
|---|---|---|
| SenseVoiceSmall (sherpa-onnx 转换版) | 实时字幕 | 上游 FunAudioLLM 权重有其自身许可（含使用限制），**务必读模型页** |
| Silero VAD (`silero_vad.onnx`) | 语音活动检测/断句 | Silero 预训练权重有独立许可（非纯 OSI），以 silero.ai 为准 |
| whisper-large-v3-turbo (MLX 转换版) | 本地精修 / 导入转写 | 源自 OpenAI Whisper（MIT）；社区转换版沿用 MIT，仍以发布页为准 |

## 说明

- 本程序内置的模型「默认路径兜底」仅为方便作者自测；任何组件、模型与路径都**不随本仓库分发**。
- 若你计划把这套东西再分发（哪怕只是公司内部），请先确认每一步都不违反上述第三方许可与本程序自身的「非商业」限制。
- 欢迎提 Issue 指出本文件中任何许可证标注错误。
