# 第三方组件与许可说明 (Third-Party Notices)

本程序（听道）自身的许可见仓库根目录的 `LICENSE`（PolyForm Noncommercial License 1.0.0，仅供个人非商业使用）。
下列第三方组件各自遵循其上游许可证；你在使用或再分发由这些组件支撑的功能时，须同时遵守相应许可。

> 下表许可证按各项目官方仓库或模型页整理。上游许可可能随版本变化，再分发前请以官方页面为准。

## 随安装包分发的组件

| 组件 | 用途 | 许可证 | 来源 |
|---|---|---|---|
| FFmpeg（BtbN win64 LGPL shared 构建） | Windows 安装版内置：音视频导入、M4A 编码、音频预处理 | LGPL-2.1-or-later（许可文本随包附带） | FFmpeg/FFmpeg · BtbN/FFmpeg-Builds |
| Pinyon Script 字体 | 侧栏与「关于」页的 Folio 手写字标，内嵌于 `index.html` | SIL Open Font License 1.1 | Google Fonts |
| Tauri 及其 Rust 依赖 | 原生窗口壳 | MIT / Apache-2.0 | tauri-apps/tauri |
| ed25519-dalek 2.2.0 / curve25519-dalek 4.1.3 及签名依赖 | 静默前端补丁签名验证，编译进原生壳 | BSD-3-Clause / MIT / Apache-2.0（许可文本随包 `program/licenses/frontend-patches.txt` 或 `program-windows/licenses/frontend-patches.txt`） | dalek-cryptography/curve25519-dalek；见 `licenses/frontend-patches.txt` |
| opencc-python-reimplemented 0.1.7 | 转写结果中文简繁统一，随程序放在 `opencc/`（含 OpenCC 词典） | Apache-2.0（`opencc/LICENSE.txt`、`opencc/NOTICE.txt`） | yichen0831/opencc-python · BYVoid/OpenCC |

macOS 安装包不内置 FFmpeg；Windows 安装器在系统缺少 Microsoft Edge WebView2 时会联网下载该运行时，其许可由微软提供。

## Python 库（用户 `pip install -r requirements.txt` 自行安装）

| 组件 | 用途 | 许可证 | 来源 |
|---|---|---|---|
| numpy | 数值/音频处理 | BSD-3-Clause | numpy/numpy |
| requests | HTTP（云端接口、更新检查） | Apache-2.0 | psf/requests |
| sherpa-onnx | SenseVoice 实时识别 + Silero VAD 断句 | Apache-2.0 | k2-fsa/sherpa-onnx |
| pywebview | 源码直接运行 `python app.py` 时的窗口 | BSD-3-Clause | r0x0r/pywebview |
| pyobjc | macOS Cocoa 绑定 | MIT | ronaldoussoren/pyobjc |
| mlx / mlx-whisper | macOS 本地 Whisper 精修与导入转写 | MIT | ml-explore/mlx · ml-explore/mlx-examples |
| faster-whisper / CTranslate2 | Windows 本地 Whisper 精修与导入转写 | MIT | SYSTRAN/faster-whisper · OpenNMT/CTranslate2 |
| PyAudioWPatch | Windows 系统声音（WASAPI loopback）与麦克风采集 | MIT（内含 PortAudio，MIT） | s0d3s/PyAudioWPatch |

## 命令行工具（用户自行安装）

| 组件 | 用途 | 许可证 |
|---|---|---|
| FFmpeg | macOS 与源码运行时的音视频导入、编码、预处理 | LGPL/GPL（视构建选项而定） |
| switchaudio-osx（可选，macOS） | 识别当前系统输出设备 | MIT |

系统声音采集使用系统自带能力（macOS ScreenCaptureKit、Windows WASAPI loopback），不需要虚拟声卡或驱动。

## 模型（用户自行下载，在「设置 → 模型与服务 → 本地模型目录」填写路径）

| 模型 | 用途 | 许可提示 |
|---|---|---|
| SenseVoiceSmall（sherpa-onnx 转换版） | 实时字幕 | 上游 FunAudioLLM 权重有其自身模型许可（含使用限制），**务必阅读模型页** |
| Silero VAD（`silero_vad.onnx`） | 语音活动检测/断句 | MIT，以 snakers4/silero-vad 为准 |
| Whisper（如 large-v3-turbo；macOS 用 MLX 转换版，Windows 用 CTranslate2 转换版） | 本地精修 / 导入转写 | 源自 OpenAI Whisper（MIT）；社区转换版通常沿用 MIT，以各发布页为准 |

## 说明

- 模型与 Python 依赖都不随本仓库或安装包分发。
- 若你计划再分发（哪怕只是公司内部），请先确认每一步都不违反上述第三方许可与本程序自身的「非商业」限制。
- 欢迎提 Issue 指出本文件中任何许可证标注错误。
