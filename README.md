<p align="center">
  <img src="./assets/readme/hero-badge.png" width="100%" alt="ting Dao · oto：本地优先录音、转写与复盘工具，支持 macOS 和 Windows">
</p>

# 听道 · 本地录音与转写

<h2 id="overview"><img src="./assets/readme/badges/overview.svg" height="40" alt="概览"></h2>

听道适用于 macOS 与 Windows，可录制系统声音与麦克风声音。支持本地模型转写和远端api转写两套通路。支持生成笔记与文稿摘要。深度集成从听→学的知识掌握链路。听道服务于：咨询服务、会议记录、私密会话、网课学习等场景。

当前版本：**v2.7.10**　·　[下载页面](https://github.com/Ayin-git1/tingdao/releases)　·　[PolyForm Noncommercial License](./LICENSE)

<h2 id="download"><img src="./assets/readme/badges/download.svg" height="40" alt="下载与安装"></h2>

- **让 Agent 帮你安装**：告诉 Agent
```powershell
读取 https://github.com/Ayin-git1/tingdao readme,从国内镜像源下载三款适合我[这里填 Mac或Windows]系统的模型，并检查运行环境，若缺少，也请你一并为我安装并配置。
```
- **macOS（Apple Silicon，macOS 12.3+）**：从 [Releases](https://github.com/Ayin-git1/tingdao/releases) 下载最新 DMG，将「听道.app」拖入「应用程序」。首次打开若被系统拦截，右键应用并选择「打开」。
- **Windows 10/11 x64**：下载最新 `听道_<版本>_x64-setup.exe` 并运行。安装器会在需要时下载 WebView2；Python 和模型需自行准备，见[运行依赖](#dependencies)和[Windows 安装步骤](#windows-setup)。
- 安装包只含程序本体及 Windows 所需的 FFmpeg；Python 环境和模型需自行准备。源码 zip 运行时仍需自行安装 FFmpeg。系统声音采集使用系统自带能力，不需要虚拟声卡。

<h2 id="features"><img src="./assets/readme/badges/features.svg" height="40" alt="核心功能"></h2>

- **录制与实时字幕**：系统声音、麦克风或混合录音；支持暂停、继续和实时字幕。
- **本地转写**：macOS 使用 MLX Whisper，Windows 使用 faster-whisper / CTranslate2；支持录音精修和音视频导入。
- **云端处理（可选）**：可选择上传音频转写，或只发送本地转写出的文字进行润色和摘要。上传前会再次确认。
- **文稿整理**：逐句时间戳与回放、说话人标记、录音中与录音后的时间线笔记、热词模板、查找和快捷键。
- **个性化**：浅色、深色和跟随系统外观；支持预设及自定义主题色。
- **导出与管理**：导出 Markdown 和音频；历史项目支持搜索、排序、批量删除与在文件管理器中打开。删除内容先移入系统回收站。

<h2 id="privacy"><img src="./assets/readme/badges/privacy.svg" height="40" alt="隐私与数据"></h2>

- 默认本地运行，无账号、遥测或自动更新检查；本地模式下录音和模型处理不离开电脑。
- 只有在云端模式确认上传后，音频才会发送给所配置的第三方服务。选择“本地转写 + 云端后制作”时，只发送文稿文字。
- 项目与设置以普通文件保存在用户数据目录，可自行备份或删除。云端 API Key 在本机配置中加密保存；这不构成抵御本机用户或恶意程序的安全边界。

<h2 id="first-use"><img src="./assets/readme/badges/first-use.svg" height="40" alt="首次使用"></h2>

1. macOS 首次录音时，在系统提示中允许「屏幕录制」和麦克风权限；听道通过系统接口采集音频，不录制屏幕画面。
2. Windows 按下方步骤准备 Python 环境；安装版已包含 FFmpeg。
3. 在「设置 → 本地模型」中填写模型路径；需要云端服务时，在「设置 → 对话模式」中配置并测试连接。
4. 在「设置 → 录音」选择麦克风输入源。系统声音采集跟随系统默认输出设备。

<h2 id="dependencies"><img src="./assets/readme/badges/dependencies.svg" height="40" alt="运行依赖"></h2>

- **系统**：macOS 安装包支持 Apple Silicon 和 macOS 12.3+；Windows 支持 10/11 x64。
- **Python**：建议 3.10。Windows 安装版默认使用 `%USERPROFILE%\tingdao-venv`；自定义解释器可通过 `TINGDAO_PY` 指定。
- **FFmpeg**：Windows 安装版已包含；macOS 和源码 zip 需要单独安装并加入 `PATH`，用于音视频导入、M4A 编码和音频预处理。macOS 可选安装 `switchaudio-osx` 以在录制中调整输出音量。
- **模型**：SenseVoiceSmall、Silero VAD 和 Whisper 模型均需自行下载，在设置中填写路径。macOS 的 MLX 模型不能用于 Windows；Windows 需使用 CTranslate2 格式。
- 系统声音采集：macOS 使用 ScreenCaptureKit，Windows 使用 WASAPI loopback，均无需虚拟声卡或额外驱动。

<h2 id="windows-setup"><img src="./assets/readme/badges/windows-setup.svg" height="40" alt="Windows 安装步骤"></h2>

适用于 Windows 10/11 x64 安装版。先从 [Releases](https://github.com/Ayin-git1/tingdao/releases) 下载并安装听道，然后在 PowerShell 中准备 Python 环境：

```powershell
winget install --id Python.Python.3.10 --exact
py -3.10 -m venv "$env:USERPROFILE\tingdao-venv"
$python = "$env:USERPROFILE\tingdao-venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install numpy requests sherpa-onnx pyaudiowpatch faster-whisper
```

Windows 安装版已包含 FFmpeg。安装 Python 后重开 PowerShell，并确认 `py -3.10 --version` 可用。下载 SenseVoiceSmall、Silero VAD 和 CTranslate2 格式 Whisper 模型，在「设置 → 本地模型」填写路径。首次录音时允许麦克风访问。安装器在系统缺少 WebView2 时会联网下载运行时；源码 zip 运行还需自行安装 FFmpeg。

源码 zip 备用启动方式：在源码目录创建环境并安装 `requirements.txt`，再运行 `python app.py`。日常使用安装版无需下载源码。

<h2 id="workflow"><img src="./assets/readme/badges/workflow.svg" height="40" alt="工作方式"></h2>

1. 采集系统声音和/或麦克风，生成实时字幕与本地录音母带。
2. 按所选模式进行本地 Whisper 精修，或在用户确认后使用云端转写与后制作。
3. 将逐句文稿、时间戳、笔记和音频保存在本地项目中，按需导出。

内部服务仅监听 `127.0.0.1`；数据默认保存在 `~/Documents/transcripts/`（macOS）或 Windows 用户文档目录，可通过 `TINGDAO_DATA` 指定 macOS 数据目录。

<h2 id="data"><img src="./assets/readme/badges/data.svg" height="40" alt="文件与数据"></h2>

源码 zip 包含 `app.py`、`index.html`、`whisper_worker.py`、`requirements.txt` 和 Tauri 原生窗口壳。Windows 的打包壳使用 `tauri-shell/program-windows/` 中的运行文件。项目录音、文稿、设置、热词和日志保存在用户数据目录，不写入应用安装目录。

<h2 id="limitations"><img src="./assets/readme/badges/limitations.svg" height="40" alt="已知限制"></h2>

- Windows 录制中切换系统默认扬声器或耳机后，需要停止并重新开始录制。
- 录制中调整输出音量仅支持 macOS。
- SenseVoice 不支持热词；热词仅用于支持它的精修和云端转写模型。
- 同步云端转写需要返回逐句时间戳；异步文件服务通常会先将音频上传到服务商的临时存储。
- Windows 安装版仍需自行安装 Python 依赖并下载模型。

<h2 id="license"><img src="./assets/readme/badges/license.svg" height="40" alt="许可"></h2>

源码采用 [PolyForm Noncommercial License 1.0.0](./LICENSE)，仅限个人非商业使用；应表述为“源码公开”，不属于允许商业使用的 OSI 开源许可。第三方库、工具和模型各自遵循其上游许可，详见 [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md)。macOS 提供 DMG，Windows 提供 NSIS 安装包，源码 zip 作为备用方式。

<h2 id="updates"><img src="./assets/readme/badges/updates.svg" height="40" alt="v2.7.10 更新"></h2>

### v2.7.10

- 完善 macOS 与 Windows 双端窗口适配：Windows 11 使用自绘标题栏、窗口控制按钮与边缘缩放；macOS 沿用现有 Tingdao.icns 图标。
- Windows 启动时自动查找已安装听道依赖的 Python 虚拟环境；也可在设置中手动选择解释器。录音和转码期间不再弹出黑色控制台窗口。
- 侧栏悬浮预览可一键转为常驻；整理摘要卡与音频条的显示和交互。

### v2.7.1

- Windows 新增本地 Whisper 识别与精修，支持 faster-whisper / CTranslate2 模型。
- Windows 安装包现包含 FFmpeg，首次配置只需另备 Python 依赖和模型。
- 更新模型填写方式，加入选择器。点击"..."开启，Whisper与SV 为文件夹选择器；VAD 断句为.onnx选择器。
- 新增录音结束后的时间线笔记，可添加、编辑和删除。
- 优化录音母带处理，保留高质量母带作为音频来源，减少不必要的转码和回放副本。
- 更新听道应用图标，并统一 README 首页与章节标题视觉样式。
- 优化项目抽屉的显示层级和开关动画效果。
- 新增界面主题色与阅读字号；行距调整。界面显示基本满足个性需求。
