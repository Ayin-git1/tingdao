# 3.1.9 前端补丁验证记录

日期：2026-10-31。仅本地构建与验证，未上传 GitHub，未替换 /Applications/听道.app。

## 通过的验收

- 相关 Node 测试 13/13；前端启动与补丁 Python 测试 13/13（包含真实 HTTP 与原生验签集成）；Rust 测试 11/11。
- 真正启动构建 App，使用临时数据目录：两项设置初始化均为 true，历史刷新 true，签名补丁状态 confirmed:true。
- 运行后 App strict/deep 签名依然有效；原生壳禁用 Python 字节码写入，避免破坏签名。
- 首启失败回退、拒绝重复尝试、错误签名/哈希、断网、跨版本、双实例锁、延迟 ACK 和签名回退指令通过。
- 只读挂载最终 DMG，arm64、3.1.9、App/音频助手/麦克风助手固定签名要求与 strict/deep 签名通过。
- app.py、frontend_patch.py、index.html、whisper_worker.py 与许可证文件的根源码 → staging → 构建 App → 挂载 DMG 哈希一致。
- 挂载镜像内的验证器接受实际发布工具签名，拒绝篡改标签；私钥未被打包。
- Finder 元数据：800×432，App(220,245)，Applications(580,245)，背景为卷内 /.background/dmg-background.tiff，没有旧磁盘镜像引用。
- 独立代码评审发现的 P2（设置/历史失败仍可能 ACK）已修复并复查通过。

## 全量检查的既有失败

Node 全量：418 项，396 通过、22 失败。用 HEAD 导出的原始源码在临时目录复跑，下面全部失败项在修改前也存在；本次无新增失败：

- all interface corner radii use a token, square corners, or an explicit circle
- all three scroll listeners use frame scheduling and passive events
- chapter outline card stays above reading tools but below global popup windows
- cleanup busy response preserves image preloads and reenables button
- each successive recording obtains a new default name
- empty and repeated cleanup leave untouched rows and their DOM intact
- explicit scroll targets cover current scrollable CSS containers and textareas
- findMatchRanges returns every non-overlapping literal occurrence
- glass controls use the intended shadow elevation
- macOS shell keeps the native Edit menu for contenteditable clipboard shortcuts
- neutral controls and dropdown surfaces use the rest material
- new recording after rename uses current time rather than previous title
- new recording from an opened manuscript also generates a fresh name
- partial cleanup retains error and never reports success
- picker is not dismissed by settings scroll and playback follow pauses during popups
- recent and group sections are rendered inside the existing history list
- settings shows total size, path and last successful cleanup
- sidebar tab track stays transparent while the selected tab keeps material
- startup-only scheduling and nonpersistent native WebView are wired
- stop waits for in-flight images before asking the backend to finish
- successful cleanup clears preloads and calls the native browsing-data API
- transcript outline level-2 items are black in light mode and readable in dark mode

Python 全量（默认沙箱）：257 项，1 failure、2 errors、3 skipped。修改前源码对照也存在这些失败：

- test_import_uses_current_setting_instead_of_previous_recording（test_asr_language）：测试提取函数缺少 unreadable_media。
- test_pause_resume_preserves_all_master_segments_and_new_session_is_separate（test_master_resume_append）：既有 master 分段断言失败。
- test_audio_range.setUpClass：默认沙箱禁止绑定本地端口。已在允许本地端口的环境单独重跑，10/10 通过。
- 默认全量跳过原生补丁集成测试；该测试已用最终 App 的验证器单独运行通过。

## 交付范围与限制

- macOS Apple Silicon DMG 已构建。Windows staging 与跨平台逻辑测试通过，但本次没有 Windows 安装包或真实 Windows 运行证据。
- p1 补丁资产与当前内置页面相同，供补丁通道验收；没有 GitHub 发布，所有后续公开上传须按发布说明操作。
- 安装版采用项目现有本地固定标识 ad-hoc 签名流程；本次没有 Apple Developer ID 签名或公证。
- 就绪确认只能判断基础启动成功，不会自动检测每个按钮或业务功能。
- 私钥位于 Git 忽略的 releases/patch-signing/private.pem，需单独备份，不能随补丁或安装包分发。

## 安装包

SHA-256：`c655ece150a62f40018541d2324d0a4bd6e5a7cd08f40153b20fe5435839d03f`。
完整签名、哈希和布局记录见 releases/3.1.9/verification.json。
