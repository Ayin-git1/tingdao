<p align="center">
  <img src="./assets/readme/hero-badge.png" width="100%" alt="ting Dao · oto：本地优先录音、转写与复盘工具，支持 macOS 和 Windows">
</p>

# 听道 · 本地录音与转写

<h2 id="overview"><img src="./assets/readme/badges/overview.svg" height="40" alt="概览"></h2>

听道适用于 macOS 与 Windows，可录制系统声音与麦克风声音。支持本地模型转写和远端api转写两套通路。支持生成笔记与文稿摘要。深度集成从听→学的知识掌握链路。听道服务于：咨询服务、会议记录、私密会话、网课学习等场景。

当前版本：**v3.1.0**　·　[下载页面](https://github.com/Ayin-git1/tingdao/releases)　·　[PolyForm Noncommercial License](./LICENSE)

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
- **文稿整理**：逐句时间戳与回放、说话人标记、AI 摘要与章节目录、录音中与录音后的时间线笔记、热词模板、查找替换和快捷键。
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
- **Python**：建议 3.10。Windows 安装版会自动索引已安装且具备听道依赖的 Python 虚拟环境；也可在设置中手动选择解释器，或通过 `TINGDAO_PY` 指定。
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
3. 精修完成后可单独生成 AI 摘要与章节目录；目录会落到真实时间戳，用于文稿标题和右侧导航。
4. 将逐句文稿、时间戳、笔记、摘要目录和音频保存在本地项目中，按需导出。

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

<h2 id="updates"><img src="./assets/readme/badges/updates.svg" height="40" alt="v3.1.0 更新"></h2>

### v3.1.0 增量更新 · 2026-10-07

本次保持版本号不变。[下载本次 macOS Apple Silicon 安装包](https://github.com/Ayin-git1/tingdao/releases/download/v3.1.0/tingdao_3.1.0_20261007_aarch64.dmg)。

- 改进录音处理与项目切换：减少处理等待，避免旧任务影响当前项目，完善退出清理和音频读取；继续录音时追加主音频，避免覆盖已有录音。
- 完善分组管理：支持在侧栏新建、原位重命名、删除和拖动排序，编辑前自动折叠分组，优化拖动反馈与自动滚动。
- 优化逐句编辑：编辑结果与撤销入口在当前段落下方展开，补足底部阅读空间，减少播放器及编辑卡片对文稿的遮挡。
- 完善图片旁排：文字笔记、标题和编辑区域随图片位置避让，调整图片插入与拖动判定，保持图文排版连贯。
- 优化回放与悬停提示：以颜色、侧边标记和轻底色强调当前句，切句时保持文字布局稳定，并区分单击播放和双击编辑。
- 完善录音反馈：开始和结束录音时显示加载提示并防止重复操作；暂停与继续录音显示等待状态，避免轮询造成图标闪烁。
- 调整增强与拟态材质的默认参数，优化侧栏预览、目录字号和单人模式提示的位置。

### v3.1.0

- 新增独立图片笔记：支持拖入、粘贴与录音中添加图片，文稿图片以双列布局展示，并可查看全部笔记、原位编辑文字笔记。
- 更新顶部导航与左侧项目栏：加入最近项目、分组与收藏切换，完善拖动分组时的自动滚动及项目状态展示。
- 完善归档流程与批量选择：项目可先归档，再从归档页选择删除。
- 新增缓存管理：处理临时文件统一存入缓存目录，可查看占用和手动清理，并在到期后的启动时按月清理。
- 新增回放临时 2 倍速加速，优化回放进度与继续播放提示。
- 更新浅色、深色界面的玻璃材质、圆角与浮层阴影，优化录音控制区及弹出面板的滚动体验。
- 整理应用菜单入口，优化 macOS 窗口与 WebView 缓存管理；同步 3.1.0 版本信息，并重绘 macOS 安装包背景。

### v3.0.0

- 将 AI 摘要从文稿精修中拆成独立任务：精修只负责修正文稿，旧摘要会在文稿变化后失效，用户可在项目页手动生成或重新生成摘要。
- 新增摘要与章节目录专用模型设置：可为摘要/目录单独填写模型名、深度思考开关和补充提示词；留空时回退到文稿精修模型。
- 摘要生成同步产出 H1/H2/H3 章节目录，并把模型时间戳重新对齐到真实文稿段；正文中插入章节标题，右侧锚点可展开目录导航。
- 优化长文稿锚点：摘要目录存在时用章节结构驱动导航，录音中隐藏锚点避免误触，并补充滚动、层级、暗色模式和目录卡片测试。
- 查找栏新增逐条替换：高亮每个命中项，替换当前命中后继续定位下一处，并复用现有逐句编辑接口。
- 重做文稿精修/摘要状态卡：从悬浮胶囊改为正文顶部低对比卡片，摘要生成入口复用同一卡片，减少对阅读区的遮挡。
- macOS 打包资源补入 `Assets.car`，确保正式包能携带图标变体资源。

### v2.7.10

- 完善 macOS 与 Windows 双端窗口适配：Windows 11 使用自绘标题栏、窗口控制按钮与边缘缩放；macOS 沿用现有 Tingdao.icns 图标。
- Windows 启动时自动索引已安装且具备听道依赖的 Python 虚拟环境；也可在设置中手动选择解释器。录音和转码期间不再弹出黑色控制台窗口。
- 新增左侧项目栏的版本与仓库信息卡；长文稿可按时间分段快速定位，并补全其交互测试。
- 优化逐字稿复制方式：可设置默认格式，按住 Option / Alt 点击复制按钮可临时选择；命令面板现可搜索项目与分组。
- 优化设置面板布局与完成提示音控制，补充左右侧栏快捷键及跨平台键位提示。

### v2.7.1

- Windows 新增本地 Whisper 识别与精修，支持 faster-whisper / CTranslate2 模型。
- Windows 安装包现包含 FFmpeg，首次配置只需另备 Python 依赖和模型。
- 更新模型填写方式，加入选择器。点击"..."开启，Whisper与SV 为文件夹选择器；VAD 断句为.onnx选择器。
- 新增录音结束后的时间线笔记，可添加、编辑和删除。
- 优化录音母带处理，保留高质量母带作为音频来源，减少不必要的转码和回放副本。
- 更新听道应用图标，并统一 README 首页与章节标题视觉样式。
- 优化项目抽屉的显示层级和开关动画效果。
- 新增界面主题色与阅读字号；行距调整。界面显示基本满足个性需求。
