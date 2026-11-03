<p align="center">
  <img src="./assets/readme/hero-badge.png" width="100%" alt="ting Dao · oto：本地优先录音、转写与复盘工具，支持 macOS 和 Windows">
</p>

# 听道 · 本地录音与转写

<h2 id="overview"><img src="./assets/readme/badges/overview.svg" height="40" alt="概览"></h2>

听道适用于 macOS 与 Windows，可录制系统声音与麦克风声音。支持本地模型转写和远端api转写两套通路。支持生成笔记与文稿摘要。深度集成从听→学的知识掌握链路。听道服务于：咨询服务、会议记录、私密会话、网课学习等场景。

当前版本：**v3.1.9.2**　·　[下载页面](https://github.com/Ayin-git1/tingdao/releases)　·　[PolyForm Noncommercial License](./LICENSE)

<h2 id="download"><img src="./assets/readme/badges/download.svg" height="40" alt="下载与安装"></h2>

- **让 Agent 帮你安装**：告诉 Agent
```powershell
读取 https://github.com/Ayin-git1/tingdao readme,从国内镜像源下载三款适合我[这里填 Mac或Windows]系统的模型，并检查运行环境，若缺少，也请你一并为我安装并配置。
```
- **macOS（Apple Silicon，macOS 12.3+）**：从 [Releases](https://github.com/Ayin-git1/tingdao/releases) 下载最新 DMG，将「听道.app」拖入「应用程序」。首次打开时，系统可能提示无法验证开发者并建议「移到废纸篓」，请不要移走，点「完成」后打开「系统设置 → 隐私与安全性」，拉到页面最底部，在听道的提示旁点击「仍要打开」，按提示输入密码验证，之后即可正常打开。
- **Windows 10/11 x64**：下载 [v3.1.2 Windows 安装包](https://github.com/Ayin-git1/tingdao/releases/download/v3.1.2/tingdao_3.1.2_x64-setup.exe) 并运行。安装器会在需要时下载 WebView2；Python 和模型需自行准备，见[运行依赖](#dependencies)和[Windows 安装步骤](#windows-setup)。
- 安装包只含程序本体及 Windows 所需的 FFmpeg；Python 环境和模型需自行准备。源码 zip 运行时仍需自行安装 FFmpeg。系统声音采集使用系统自带能力，不需要虚拟声卡。

<h2 id="features"><img src="./assets/readme/badges/features.svg" height="40" alt="核心功能"></h2>

- **录制与实时字幕**：系统声音、麦克风或混合录音；录音中可随时切换来源而不中断；支持暂停、继续和实时字幕。
- **本地转写**：macOS 使用 MLX Whisper，Windows 使用 faster-whisper / CTranslate2；支持录音精修和音视频导入；转写语言可选简体中文、繁体中文、英语或自动识别。
- **云端处理（可选）**：可选择上传音频转写，或只发送本地转写出的文字进行润色和摘要。上传前会再次确认。
- **文稿整理**：逐句时间戳与回放、说话人标记、AI 摘要与章节目录、录音中与录音后的时间线笔记（macOS 录音中可用 iPhone 直接拍照插入）、热词模板、搜索面板与替换、快捷键。
- **个性化**：浅色、深色和跟随系统外观；支持预设及自定义主题色、阅读字号与行距、摘要背景（白色 / 杂志灰）。
- **导出与分享**：导出 Markdown 和音频；文稿可单份或多选打包成完整笔记包（zip），连同录音、时间线笔记、图片、摘要目录和课后笔记一起发给别人，对方用「导入笔记」即可原样恢复。
- **长文稿流畅**：9 小时以上的逐字稿也能顺畅打开、滚动和按目录跳转，见 [v3.1.8 更新](https://github.com/Ayin-git1/tingdao/releases/tag/v3.1.8)。
- **项目管理**：历史项目支持搜索、排序、分组、归档、批量删除与在文件管理器中打开。删除内容先移入系统回收站。

<h2 id="privacy"><img src="./assets/readme/badges/privacy.svg" height="40" alt="隐私与数据"></h2>

- 默认本地运行，无账号或遥测；本地模式下录音和模型处理不离开电脑。
- 启动后默认向 GitHub Release 查询是否有新版本，只读取公开发布信息、不上传任何数据；可在「设置 → 关于」关闭自动检查。
- 只有在云端模式确认上传后，音频才会发送给所配置的第三方服务。选择“本地转写 + 云端后制作”时，只发送文稿文字。
- 项目与设置以普通文件保存在用户数据目录，可自行备份或删除。云端 API Key 在本机配置中加密保存；这不构成抵御本机用户或恶意程序的安全边界。

<h2 id="first-use"><img src="./assets/readme/badges/first-use.svg" height="40" alt="首次使用"></h2>

1. 首次打开（含老用户升级到 3.1.8 后）需先设置一个用户名：1–24 个英文字母，中文名可用拼音，用于分享笔记包时署名，之后可在「设置 → 外观与阅读」修改。
2. macOS 首次录音时，在系统提示中允许「屏幕录制」和麦克风权限；听道通过系统接口采集音频，不录制屏幕画面。
3. Windows 按下方步骤准备 Python 环境；安装版已包含 FFmpeg。
4. 在「设置 → 模型与服务 → 本地模型目录」中填写模型路径；需要云端服务时，在同页「云端」中配置并测试连接，再到「设置 → 录音与转写 → 对话模式」选择「云端」。
5. 在「设置 → 录音与转写」选择录音来源和麦克风输入源。系统声音采集跟随系统默认输出设备。

<h2 id="guide"><img src="./assets/readme/badges/guide.svg" height="40" alt="使用说明"></h2>

第一次打开听道（或从旧版升级到 3.1.7 及以后）时，项目栏里会有一份「听道使用说明」。它本身就是一份带录音的文稿，下面这些操作都能在里面直接试，看完归档或删掉即可。Windows 上把 ⌘ 换成 Ctrl，⌥ 换成 Alt。

**录音时**

- ⌘⇧R 开始录音，点计时条右边的小方块结束。录到一半可以换录音来源，录音不会断。
- ⌘N 记一句笔记，回车保存，时间点算在按回车的那一刻。
- 图片可以直接拖进窗口，或按 ⌘V 粘贴；macOS 上按 ⌘⇧P 用 iPhone 拍照。图片都挂在当下的时间点上。

**看稿时**

- 点任意一段，从那里开始播放；空格暂停，↑ ↓ 跳句，按住 → 临时两倍速，松手恢复。
- 双击一段就地改字，改错了点「撤销这一处」。
- 选中文字会浮出工具栏：加粗、下划线、文字颜色、背景色，或把这句引用到笔记里。选中后 ⌘B、⌘U 也能直接用。
- 鼠标移到文稿右边那列细刻度上，会展开章节目录。

**文稿里的图片**

<p align="center"><img src="./assets/demo/note-images/drop-zones.png" width="680" alt="图片拖到某一段上时：落在上沿或下沿单独占一行，落在左侧或右侧靠边并让文字绕排"></p>

- 把图片拖到某一段上，松手的位置决定排法：上沿或下沿单独占一行，左侧或右侧靠边、文字绕着排。放好的图还能再拖，拖右下角手柄缩放，双击用系统看图软件打开。
- 在一段上右键「添加时间线笔记」，卡片里可以写字、放图。写的时候右键图片，有嵌入型、四周型环绕等五种排法。

**分享笔记**

- 在项目上右键「导出分享」，或点文稿工具栏的导出按钮；多选项目后也能批量导出。生成的是一个 zip 笔记包，打包时左下角会显示已处理多少 MB。
- 收到别人的笔记包，点侧栏「导入音频 / 视频」下方的「导入笔记」，直接选 zip（无需解压）或解压后的文件夹。录音、图片和笔记排版都会恢复；同名笔记自动加「（1）」，不会覆盖你已有的内容。

**容易漏掉的**

- 摘要生成后，生成按钮会收起来。鼠标在「AI 摘要」那一行停一两秒，右边才会出现重新生成。
- 项目栏收起后，把鼠标移到左上角的开关按钮上，项目栏会临时浮出来。
- 按住 ⌥ 再点复制，可以临时换成带时间戳的 Markdown 或剧本格式；⌘E 直接复制纯文本。
- 超过 2 小时的文稿打开时会先显示「正在加载文稿…」，正文排好后自动出现，期间可以继续操作别的项目。
- 记不住快捷键就按 ⌘/。

<h2 id="models"><img src="./assets/readme/badges/models.svg" height="40" alt="推荐模型组合"></h2>

作者日常使用的云端组合，全部来自阿里云百炼（DashScope），供参考。在「设置 → 模型与服务」中服务商选「Qwen百炼」，接口地址填 `https://dashscope.aliyuncs.com/api/v1` 并填入百炼 API Key；对话模式选「云端转写+后制作」。

| 用途 | 设置项 | 模型名 | 深度思考 |
|---|---|---|---|
| 音频转写 | 转写模型名 | `paraformer-v2` | — |
| 文稿精修 | 文稿精修 | `qwen-long` | 关 |
| 摘要与章节目录 | 摘要目录生成模型 | `qwen3.8-flash` | 关 |
| 笔记 | 笔记模型 | `deepseek-v4.1-flash` | 开 |

**摘要目录为什么推荐 `qwen3.8-flash`**：在作者实际使用中，它对全文的理解比 DeepSeek 更清晰，长逐字稿里哪里是新章节、哪里只是例子或补充，判断得明显更准；逻辑梳理和给内容打标签（H1 章节、H2 要点、H3 细节）的能力很突出，目录层级更干净，章节标题也能抓住每段主要讲的内容。关闭深度思考即可获得很好的效果，速度更快、更省 token。

模型名需与百炼控制台中的名称完全一致；费用按百炼计费规则由服务商收取。若不想上传音频，可改用「本地转写+云端后制作」，只把文稿文字发给精修、摘要和笔记模型。

<h2 id="dependencies"><img src="./assets/readme/badges/dependencies.svg" height="40" alt="运行依赖"></h2>

- **系统**：macOS 安装包支持 Apple Silicon 和 macOS 12.3+；Windows 支持 10/11 x64。
- **Python**：建议 3.10。Windows 安装版会自动索引已安装且具备听道依赖的 Python 虚拟环境；也可在设置中手动选择解释器，或通过 `TINGDAO_PY` 指定。
- **FFmpeg**：Windows 安装版已包含；macOS 和源码 zip 需要单独安装并加入 `PATH`，用于音视频导入、M4A 编码和音频预处理。macOS 录制中的输出音量直接通过系统 CoreAudio 调节；可选安装 `switchaudio-osx`，便于准确识别当前输出设备。
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

Windows 安装版已包含 FFmpeg。安装 Python 后重开 PowerShell，并确认 `py -3.10 --version` 可用。下载 SenseVoiceSmall、Silero VAD 和 CTranslate2 格式 Whisper 模型，在「设置 → 模型与服务 → 本地模型目录」填写路径。首次录音时允许麦克风访问。安装器在系统缺少 WebView2 时会联网下载运行时；源码 zip 运行还需自行安装 FFmpeg。

源码 zip 备用启动方式：在源码目录创建环境并安装 `requirements.txt`，再运行 `python app.py`。日常使用安装版无需下载源码。

<h2 id="workflow"><img src="./assets/readme/badges/workflow.svg" height="40" alt="工作方式"></h2>

1. 采集系统声音和/或麦克风，生成实时字幕与本地录音母带。
2. 按所选模式进行本地 Whisper 精修，或在用户确认后使用云端转写与后制作。
3. 精修完成后可单独生成 AI 摘要与章节目录；目录会落到真实时间戳，用于文稿标题和右侧导航。
4. 将逐句文稿、时间戳、笔记、摘要目录和音频保存在本地项目中，按需导出。

内部服务仅监听 `127.0.0.1`；数据默认保存在系统「文档」目录下的 `transcripts/`（macOS 为 `~/Documents/transcripts/`，Windows 跟随「文档」文件夹的实际位置），两个平台都可通过环境变量 `TINGDAO_DATA` 改到其他目录。

<h2 id="data"><img src="./assets/readme/badges/data.svg" height="40" alt="文件与数据"></h2>

源码 zip 包含 `app.py`（后端）、`index.html`（界面）、`whisper_worker.py` / `whisper_worker_windows.py`（本地精修）、`tingdao-mix.swift`（macOS 采集助手源码）、`opencc/`（随包附带的中文简繁转换库）、`requirements.txt` 和 `tauri-shell/` 原生窗口壳。打包时程序本体会先复制到 `tauri-shell/program/`（macOS）或由 `npm run stage:windows` 复制到 `tauri-shell/program-windows/`（Windows），这两个目录是生成产物，不入库。项目录音、文稿、设置、热词和日志保存在用户数据目录，处理缓存在其中的 `.cache/`，均不写入应用安装目录。

<h2 id="limitations"><img src="./assets/readme/badges/limitations.svg" height="40" alt="已知限制"></h2>

- Windows 录制中切换系统默认扬声器或耳机后，需要停止并重新开始录制。
- 录制中调整输出音量仅支持 macOS。
- SenseVoice 不支持热词；热词仅用于支持它的精修和云端转写模型。
- 同步云端转写需要返回逐句时间戳；异步文件服务通常会先将音频上传到服务商的临时存储。
- Windows 安装版仍需自行安装 Python 依赖并下载模型。

<h2 id="license"><img src="./assets/readme/badges/license.svg" height="40" alt="许可"></h2>

源码采用 [PolyForm Noncommercial License 1.0.0](./LICENSE)，仅限个人非商业使用；应表述为“源码公开”，不属于允许商业使用的 OSI 开源许可。第三方库、工具和模型各自遵循其上游许可，详见 [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md)。macOS 提供 DMG，Windows 提供 NSIS 安装包，源码 zip 作为备用方式。

<h2 id="updates"><img src="./assets/readme/badges/updates.svg" height="40" alt="v3.1.9.2 更新"></h2>

### v3.1.9.2 · 2026-11-03

[下载 macOS Apple Silicon 安装包](https://github.com/Ayin-git1/tingdao/releases/download/v3.1.9.2/tingdao_3.1.9.2_aarch64.dmg)。本版本暂无 Windows 安装包，Windows 用户请继续使用 v3.1.2。

- **倍速多一档**：播放条的倍速按钮改为点开选择，可选 0.75x、1x、1.25x、1.5x、2x，每个项目仍单独记住。
- **回到上次读到的位置**：重新打开有阅读位置的文稿时，正文先在后台排好、定位完成后再显示，不会先闪一下文稿开头。
- **侧栏开合更顺**：长文稿在侧栏展开收起时跳过正文重排，动画不再一顿一顿；主页卡片跟着主区平滑伸缩、文字全程可见，列数变化时卡片从原位滑到新位。
- 文稿加载骨架改为直角墨条，从左向右逐条长出，并带一道整齐扫过的流光。
- 「精修」按钮改用深一档的主题色底配白字，浅色主题下也清楚；深色模式下为纯黑底白字。
- 内置 3.1.9.1 期间发布的全部界面补丁（#2–#7）：文稿插图书签与悬停预览、深色模式下分组标签与提示气泡不再白底白字、多选工具栏文字不再折行等，无需再单独下载。

更早版本的更新说明见 [下载页面](https://github.com/Ayin-git1/tingdao/releases)，每个版本的页面顶部都有对应安装包的直接下载链接。
