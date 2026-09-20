# 听道项目工作记忆

本文件记录已经验证的项目运行、测试和打包经验，供后续工作参考。

## 维护要求

- 每次确认新的运行机制、修复根因、打包约定或重要限制后，都要及时更新本文件。
- 只记录已验证的事实；推测需标明为“待验证”。
- 代码、测试版 App 或打包流程变更后，检查本文件是否仍准确；过期内容应在同次变更中修正。

## 当前已验证经验

### 测试版 App 与源码

- 测试版 App 仅用于快速测试，不作为 DMG 正式安装版的修改目标。
- 不修改 `/Applications/听道.app` 或任何 DMG 安装版文件，除非用户明确要求。
- 当前 `/Users/ayin/Applications/听道-测试版.app` 使用带 `test-source` feature 编译的 Tauri 壳；它优先加载编译时写入的本项目源码目录 `/Users/ayin/SkillsHub/tingdao-v1.0.1`。
- 测试版不使用 App 包内的 `Contents/Resources/program/` 副本作为运行依赖；普通 Finder 双击也能加载源码，无需设置 `TINGDAO_HOME`。
- 测试版包内旧 `Contents/Resources/program/` 已移至废纸篓，不再保留第二份运行副本。
- 直接把 App 包内 `program` 替换为指向源码的符号链接不可用：macOS 代码签名不允许资源链接指向包外。必须使用测试壳的 `test-source` feature。
- 测试壳构建命令：`TINGDAO_TEST_SOURCE_DIR=/Users/ayin/SkillsHub/tingdao-v1.0.1 cargo build --release --features test-source`（在 `tauri-shell/` 目录执行）；构建产物仅替换测试版的 `Contents/MacOS/tingdao-shell` 并重新签名。
- 正式 DMG 构建绝不启用 `test-source` feature；它仍使用包内自包含资源。
- 测试版 App 的目标应是引用本项目 `/Users/ayin/SkillsHub/tingdao-v1.0.1` 内的完整文件集合，避免在源码目录外维护另一份独立的运行依赖副本。

### mix 音频助手

- macOS 的 `mix` 和 `system` 录音模式依赖根目录可执行文件 `tingdao-mix`；`app.py` 会从自身所在目录寻找它。
- 当前源码根目录已有 arm64 可执行文件 `tingdao-mix`。热测试版启动源码 `app.py` 时，通过 `TINGDAO_SCK_HELPER` 指向包内 `Contents/MacOS/tingdao-mix`；该副本必须随测试壳重新签名，避免 ScreenCaptureKit 由包外独立进程申请 TCC 权限。
- `tingdao-mix.swift` 是入库源码；`tingdao-mix` 及 `tauri-shell/program/` 是打包阶段生成/暂存内容，不纳入 Git。
- 正式 DMG 打包前必须检查包内 `Contents/Resources/program/` 同时具备 `app.py`、`index.html`、`whisper_worker.py` 与可执行的 `tingdao-mix`；任一缺失即停止发布。

### 高保真麦克风助手

- 仅麦克风模式的测试壳会通过 `TINGDAO_MIC_APP` 强制使用 `/Users/ayin/Applications/听道-测试版.app/Contents/Resources/TingdaoMic.app`，不是源码目录的 `TingdaoMic.app`。每次修改该助手后，必须同步其 `Contents/MacOS/TingdaoMic` 到测试壳内嵌副本，并重新签名内嵌 App 与外层测试 App。
- 已验证：若只更新源码副本，旧内嵌助手会忽略 `--master-rate-file`，导致后端报“高保真母带初始化失败：rate.* 不存在”。`tests/test_mic_helper_deployment.py` 会比较两个二进制，防止再次遗漏。
- 已验证：复用 VPIO 的大 render 缓冲时，`AudioUnitRender` 前每个 `AudioBuffer.mDataByteSize` 必须按本次 `inNumberFrames` 设置，不能直接报最大预分配容量。后者会在 512 帧边界产生约 -7 dBFS 的跳变，听感为高频波动/电流声；`tests/test_mic_capture_pipeline.py` 保护此约束。
- 已验证：VPIO 的输出静音回调与输入采集回调必须分开注册；输入使用 `kAudioOutputUnitProperty_SetInputCallback` 的 element 1，输出使用 element 0 的 render callback。仅在输出回调里兼做输入拉取会造成边界爆点。测试版当前还关闭 `kAUVoiceIOProperty_VoiceProcessingEnableAGC`，避免自动增益把人声和底噪一起抬高。

### macOS 权限与签名

- “系统声音录制”依赖 macOS 的“屏幕与系统音频录制”权限，不等同于麦克风权限；首次使用时由用户在系统设置中授权，应用不能预授权或绕过。
- 热测试版必须使用稳定的 ad-hoc designated requirement：测试 App 为 `local.tingdao.test`，源码 Mix 助手为 `local.tingdao.mix`。不要只用默认 ad-hoc `cdhash`，否则每次重签名/重编译都会生成新身份并导致 TCC 重复索权。
- 热测试版重新编译或替换壳后，复制源码 `tingdao-mix` 至测试 App 的 `Contents/MacOS/`，并与测试 App 一同以固定 identifier requirement 签署；源码 `app.py` 仅在 `TINGDAO_SCK_HELPER` 存在时使用该包内路径。
- 每次修改测试 App 的 `CFBundleIdentifier` 或重新签名后，必须用 LaunchServices `lsregister -u` 再 `lsregister -f` 重新注册该 App，并以 `mdls` 确认系统元数据已更新；否则“屏幕与系统音频录制”面板可能继续把权限归到同名旧备份。
- 正式 DMG 不使用本地 ad-hoc 方案：使用固定 Apple Developer ID Application 证书签署 App、包内 Mix 助手及其它嵌入可执行文件，并做 notarization。正式版保持固定正式 Bundle ID 与同一 Developer ID，测试版使用独立 Bundle ID，避免权限记录冲突。
