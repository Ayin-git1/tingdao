#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

// 听道 tauri 壳: 窗口底子 + 后端进程归属方。
// 职责: 起 python 后端(headless) → 读它回报的空闲端口 → 按该端口开窗; 窗口退出时收掉后端, 不留孤儿进程。
// 后端/解释器路径读环境变量, 缺省回落到通用约定路径 —— 换机器改环境变量即可, 不必重编。
// 端口不再写死: 后端向 OS 现取一个真正空闲的回环端口, 再经壳指定的临时端口文件回报过来,
// 从根上避免「默认端口被别的程序占了就起不来 / 抢不到端口显示空白窗」。

use std::fs::File;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};
#[cfg(target_os = "macos")]
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
// 不透明白底只给 mac 用(见 open_main_window 的 cfg 分支), Windows 构建里没人引用它 ——
// 跟着 cfg 走, 免得白留一条 unused import 警告。
#[cfg(not(target_os = "windows"))]
use tauri::utils::config::Color;

const READY_TIMEOUT_SECS: u64 = 60;
const SERVE_TIMEOUT_SECS: u64 = 10;
const MICROPHONE_MODES_MENU_ID: &str = "microphone_modes";
const SHUTDOWN_TIMEOUT_SECS: u64 = 35;
const REPOSITORY_URL: &str = "https://github.com/Ayin-git1/tingdao";

// 只有本进程亲手拉起的那份后端才归我们关; 端口文件也只由本进程创建、退出时清掉。
static BACKEND: LazyLock<Mutex<Option<Child>>> = LazyLock::new(|| Mutex::new(None));
static PORTFILE: LazyLock<Mutex<Option<PathBuf>>> = LazyLock::new(|| Mutex::new(None));
static BACKEND_PORT: LazyLock<Mutex<Option<u16>>> = LazyLock::new(|| Mutex::new(None));

fn is_repository_url(url: &str) -> bool {
    url.trim_end_matches('/') == REPOSITORY_URL
}

fn open_repository_url(url: &str) {
    if !is_repository_url(url) {
        return;
    }
    #[cfg(target_os = "macos")]
    let _ = Command::new("open").arg(url).spawn();
    #[cfg(target_os = "windows")]
    let _ = Command::new("rundll32.exe")
        .args(["url.dll,FileProtocolHandler", url])
        .spawn();
    #[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
    let _ = Command::new("xdg-open").arg(url).spawn();
}

fn bundled_program_dir(resource_dir: &Path) -> PathBuf {
    resource_dir.join(if cfg!(windows) {
        "program-windows"
    } else {
        "program"
    })
}

fn runtime_program_candidates(
    resource_dir: Option<std::path::PathBuf>,
    configured_program: Option<std::path::PathBuf>,
    home: &Path,
) -> Vec<std::path::PathBuf> {
    let mut candidates = Vec::new();
    #[cfg(feature = "test-source")]
    candidates.push(test_source_dir());
    if let Some(resources) = resource_dir {
        candidates.push(bundled_program_dir(&resources));
    }
    if let Some(program) = configured_program {
        candidates.push(program);
    }
    candidates.push(home.join("tingdao"));
    candidates
}

fn default_python_path(home: &Path, windows: bool) -> PathBuf {
    let mut path = home.join("tingdao-venv");
    if windows {
        path.extend(["Scripts", "python.exe"]);
    } else {
        path.extend(["bin", "python"]);
    }
    path
}

/// 从 venv 根取解释器路径。与 default_python_path 同一套约定, 只是拆开好复用。
fn python_bin(venv: &Path, windows: bool) -> PathBuf {
    if windows {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

/// 听道特征依赖: 命中任意一条就认为"像是给听道装过的环境"。
/// 只看 site-packages 里的目录名, 绝不启动解释器 —— import torch 要十几秒, 挂在启动路径上不可接受。
const PROBE_PACKAGES: [&str; 5] = ["sherpa_onnx", "faster_whisper", "modelscope", "funasr", "torch"];

/// 遍历目录时会跳开的名字: 大而无用(下载、回收站、依赖树), 扫了只会白烧时间。
const SCAN_SKIP_DIRS: [&str; 6] = [
    "AppData",
    "Downloads",
    "node_modules",
    "$RECYCLE.BIN",
    "OneDrive",
    "WPSDrive",
];

fn site_packages_of(venv: &Path, windows: bool) -> Option<PathBuf> {
    if windows {
        let sp = venv.join("Lib").join("site-packages");
        return sp.is_dir().then_some(sp);
    }
    // unix 下中间夹着 python3.x 一层, 版本号不固定, 只能枚举
    let lib = venv.join("lib");
    std::fs::read_dir(lib).ok()?.flatten().find_map(|e| {
        let sp = e.path().join("site-packages");
        sp.is_dir().then_some(sp)
    })
}

/// 轻量校验: 这个 venv 里装没装听道要用的包。
fn has_tingdao_deps(venv: &Path, windows: bool) -> bool {
    let Some(sp) = site_packages_of(venv, windows) else {
        return false;
    };
    let Ok(entries) = std::fs::read_dir(&sp) else {
        return false;
    };
    entries.flatten().any(|e| {
        let name = e.file_name().to_string_lossy().to_lowercase();
        // 包目录(sherpa_onnx)与发行元数据(sherpa_onnx-1.10.0.dist-info / sherpa-onnx-…)都算
        PROBE_PACKAGES.iter().any(|pkg| {
            name.starts_with(pkg) || name.starts_with(&pkg.replace('_', "-"))
        })
    })
}

/// 按给定顺序校验候选 venv: 第一个「解释器在、依赖齐」的直接采纳并返回。
///
/// 做成独立函数是为了「逐档就地校验」这个契约能被单测钉住 —— 它是惰性探测的心脏:
/// 早档命中就不再往下看, 家目录浅扫那种贵活才有机会被跳过。
/// seen 负责跨批次去重(①–④ 查过的, ⑤ 浅扫再撞见就不必重复校验);
/// trail 累积「看过但不合格」的解释器, 供全部落空时一次性摊给用户。
fn pick_ready(
    venvs: impl IntoIterator<Item = PathBuf>,
    windows: bool,
    seen: &mut Vec<PathBuf>,
    trail: &mut Vec<String>,
) -> Option<PathBuf> {
    for venv in venvs {
        if seen.contains(&venv) {
            continue;
        }
        seen.push(venv.clone());
        let py = python_bin(&venv, windows);
        // 约定路径在本机根本不存在 = 不算一次尝试, 别拿去污染失败清单(那会淹没真正的线索)
        if !py.is_file() {
            continue;
        }
        if has_tingdao_deps(&venv, windows) {
            return Some(py);
        }
        trail.push(format!("  · {} —— 缺听道依赖", py.display()));
    }
    None
}

/// 浅扫 venv: 深度 ≤2、访问目录数 ≤400、限时 700ms。
/// 预算是硬约束 —— 这活儿发生在双击到开窗之间, 不能退化成一次家目录遍历。
fn scan_for_venvs(base: &Path, started: Instant, out: &mut Vec<PathBuf>) {
    let mut queue = vec![(base.to_path_buf(), 0usize)];
    let mut visited = 0usize;
    while let Some((dir, depth)) = queue.pop() {
        if started.elapsed() > Duration::from_millis(700) || visited > 400 {
            return;
        }
        visited += 1;
        if dir.join("pyvenv.cfg").is_file() {
            out.push(dir);
            continue; // venv 内部不必再钻
        }
        if depth >= 2 {
            continue;
        }
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with('.') || SCAN_SKIP_DIRS.iter().any(|s| name.eq_ignore_ascii_case(s)) {
                continue;
            }
            if entry.file_type().map(|t| t.is_dir()).unwrap_or(false) {
                queue.push((entry.path(), depth + 1));
            }
        }
    }
}

/// 设置文件的落点。必须与 app.py 的推导完全同源(那里是 DATA_DIR/.settings.json):
/// TINGDAO_DATA 整体搬家优先, 否则系统「文档」/transcripts —— 注意要拿 Known Folder
/// 的真实位置(本机「文档」常被重定向到别的盘), tauri 的 document_dir 正是走这条路。
fn settings_file_path(app: &tauri::App) -> Option<PathBuf> {
    if let Some(data) = std::env::var_os("TINGDAO_DATA") {
        return Some(PathBuf::from(data).join(".settings.json"));
    }
    let documents = app
        .path()
        .document_dir()
        .ok()
        .or_else(|| {
            std::env::var_os("USERPROFILE")
                .map(|h| PathBuf::from(h).join("Documents"))
        })?;
    Some(documents.join("transcripts").join(".settings.json"))
}

/// 定位后端解释器。
///
/// 难点不是「找一个 python.exe」而是「找到装齐听道依赖的那一个」: 一台机器上常年并存
/// 系统 Python、py 启动器、uv/conda 托管环境, 挑中一个没装依赖的, 后端照样能起来,
/// 直到点录音才报「设置→本地模型」—— 比启动就报错更难排查。所以除 TINGDAO_PY(用户明示,
/// 原样尊重)之外, 每个候选都要过一遍 has_tingdao_deps 才敢采纳。
/// 全程把试过的位置与判定记进 trail, 供失败时一次性摊给用户看。
fn find_python(
    resource_dir: Option<&Path>,
    settings_file: Option<&Path>,
    home: &Path,
    windows: bool,
) -> Result<PathBuf, String> {
    // ⓪ 设置面板里填的解释器(最高优先): UI 是产品的正式入口, 用户在面板上填的应当最权威;
    //    TINGDAO_PY 退一位, 留给开发机临时覆盖探测结果。填了但文件不存在就明确报错 ——
    //    静默忽略回落探测, 用户会以为改了没生效。
    if let Some(sf) = settings_file {
        if let Ok(text) = std::fs::read_to_string(sf) {
            let pick = serde_json::from_str::<serde_json::Value>(&text)
                .ok()
                .and_then(|v| {
                    v.get("python_path")
                        .and_then(|s| s.as_str())
                        .map(|s| s.trim().to_string())
                })
                .filter(|p| !p.is_empty());
            if let Some(p) = pick {
                let py = PathBuf::from(&p);
                if py.is_file() {
                    return Ok(py);
                }
                return Err(format!(
                    "设置里指定的 Python 解释器不存在：{p}\n可到「设置 → 本地模型目录 → Python 解释器」改回。"
                ));
            }
        }
    }

    if let Some(explicit) = std::env::var_os("TINGDAO_PY") {
        let py = PathBuf::from(explicit);
        if py.is_file() {
            return Ok(py);
        }
        return Err(format!(
            "环境变量 TINGDAO_PY 指向的解释器不存在：{}",
            py.display()
        ));
    }

    // ① 包内自带(为「装上就能用」的自包含包预留) → ② exe 同级 → ③ 约定路径 → ④ 源码目录旁。
    //    这四档都是 O(1) 的确定性路径, 逐档就地校验、命中即返回。
    let mut explicit: Vec<PathBuf> = Vec::new();
    if let Some(resources) = resource_dir {
        explicit.push(resources.join("python"));
        explicit.push(resources.join("tingdao-venv"));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            explicit.push(dir.join("tingdao-venv"));
        }
    }
    explicit.push(home.join("tingdao-venv"));
    if let Ok(source) = std::env::var("TINGDAO_HOME") {
        let source = PathBuf::from(source);
        explicit.push(source.join(".venv"));
        explicit.push(source.join("tingdao-venv"));
        if let Some(parent) = source.parent() {
            explicit.push(parent.join("tingdao-venv"));
        }
    }

    let mut seen: Vec<PathBuf> = Vec::new();
    let mut trail: Vec<String> = Vec::new();
    if let Some(py) = pick_ready(explicit, windows, &mut seen, &mut trail) {
        return Ok(py);
    }

    // ⑤ 前四档全落空, 才动用浅扫(找 pyvenv.cfg; 深度 ≤2、400 目录、700ms 预算)。
    //    惰性是重点: 上一版先攒齐所有候选(含浅扫)再统一校验, 等于机器上明明有 ~/tingdao-venv、
    //    第一档就该命中, 却每次启动都先把家目录的 700ms 预算烧完才开始判断。
    let mut scanned = Vec::new();
    let started = Instant::now();
    scan_for_venvs(home, started, &mut scanned);
    for base in ["LOCALAPPDATA", "APPDATA"] {
        if let Some(dir) = std::env::var_os(base) {
            scan_for_venvs(Path::new(&dir), started, &mut scanned);
        }
    }
    if let Some(py) = pick_ready(scanned, windows, &mut seen, &mut trail) {
        return Ok(py);
    }

    if trail.is_empty() {
        trail.push(format!(
            "  · 未找到任何虚拟环境（查过 {}、包内资源、exe 同级与源码目录，并浅扫了家目录）",
            default_python_path(home, windows).display()
        ));
    }
    Err(format!(
        "找不到可用的 Python 环境。已试过：\n{}\n\
         请二选一：① 设环境变量 TINGDAO_PY 指向装好依赖的解释器；\n\
         ② 在 {} 建虚拟环境并 pip install -r requirements.txt。",
        trail.join("\n"),
        home.join("tingdao-venv").display()
    ))
}

/// 热测试版在编译时写入源码目录。正式版不会编入这段路径，保持完全自包含。
#[cfg(feature = "test-source")]
fn test_source_dir() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("TINGDAO_TEST_SOURCE_DIR"))
}

/// ScreenCaptureKit 助手必须位于测试 App 包内，TCC 才能稳定归属其录屏权限。
#[cfg(feature = "test-source")]
fn test_sck_helper_path(contents: &Path) -> std::path::PathBuf {
    contents.join("MacOS").join("tingdao-mix")
}

/// 麦克风模式助手必须以独立 .app 身份经 LaunchServices 启动；测试壳也必须用包内副本，
/// 不能悄悄落回开发目录，否则 TCC/签名与用户实际运行版本不一致。
#[cfg(feature = "test-source")]
fn test_mic_app_path(contents: &Path) -> std::path::PathBuf {
    contents.join("Resources").join("TingdaoMic.app")
}

fn port_open(port: u16) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn request_microphone_modes(port: u16) -> Result<(), String> {
    let mut stream =
        TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_secs(2))
            .map_err(|e| format!("无法连接录音服务：{e}"))?;
    let body = r#"{"mode":"mic"}"#;
    write!(stream, "POST /api/microphone_modes HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body)
        .map_err(|e| format!("无法请求系统麦克风模式：{e}"))?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| format!("无法读取系统麦克风模式响应：{e}"))?;
    if response.contains("\"ok\": true") {
        Ok(())
    } else {
        Err("请先开始“仅麦克风”录制，再从“听道”菜单打开麦克风模式。".to_string())
    }
}

fn recording_exit_message(response: &str) -> Option<&'static str> {
    let (_, body) = response.split_once("\r\n\r\n")?;
    let status: serde_json::Value = serde_json::from_str(body).ok()?;
    match status.get("state")?.as_str()? {
        "recording" => Some("正在录制中，退出后项目将自动保存"),
        "paused" => Some("录制已暂停，退出后项目将自动保存"),
        _ => None,
    }
}

fn confirm_recording_exit() -> bool {
    let Some(port) = *BACKEND_PORT.lock().unwrap() else { return true };
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_secs(2)) else { return true };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    if stream.write_all(b"GET /api/status HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").is_err() {
        return true;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() { return true; }
    let Some(message) = recording_exit_message(&response) else { return true };
    #[cfg(target_os = "macos")]
    {
        let script = format!("button returned of (display alert \"退出听道\" message {:?} buttons {{\"取消\", \"退出并保存\"}} default button \"取消\" cancel button \"取消\")", message);
        return Command::new("osascript").args(["-e", &script]).output()
            .map(|output| exit_dialog_confirmed(output.status.success(), &String::from_utf8_lossy(&output.stdout)))
            .unwrap_or(false);
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::ffi::OsStrExt;
        let title: Vec<u16> = std::ffi::OsStr::new("退出听道").encode_wide().chain(Some(0)).collect();
        let message: Vec<u16> = std::ffi::OsStr::new(message).encode_wide().chain(Some(0)).collect();
        #[link(name = "user32")]
        extern "system" {
            fn MessageBoxW(hwnd: *mut std::ffi::c_void, text: *const u16, caption: *const u16, kind: u32) -> i32;
        }
        return unsafe { MessageBoxW(std::ptr::null_mut(), message.as_ptr(), title.as_ptr(), 0x141) == 1 };
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    false
}

fn exit_dialog_confirmed(success: bool, button: &str) -> bool {
    success && button.trim() == "退出并保存"
}

fn request_shutdown(port: u16) {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    if let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_secs(2)) {
        let _ = stream.write_all(
            b"POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        );
    }
}

#[cfg(target_os = "macos")]
fn app_menu<R: tauri::Runtime>(app: &tauri::AppHandle<R>) -> tauri::Result<Menu<R>> {
    let microphone_modes = MenuItem::with_id(
        app,
        MICROPHONE_MODES_MENU_ID,
        "麦克风模式…",
        true,
        None::<&str>,
    )?;
    let edit_menu = Submenu::with_items(
        app,
        "编辑",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;
    Menu::with_items(
        app,
        &[&edit_menu, &Submenu::with_items(
            app,
            "听道",
            true,
            &[
                &microphone_modes,
                &PredefinedMenuItem::separator(app)?,
                &PredefinedMenuItem::quit(app, None)?,
            ],
        )?],
    )
}

/// 读后端回报的端口号; 文件还没写好 / 内容非法就返回 None, 交给上层轮询。
fn read_portfile(path: &Path) -> Option<u16> {
    let mut s = String::new();
    File::open(path).ok()?.read_to_string(&mut s).ok()?;
    s.trim().parse::<u16>().ok().filter(|p| *p > 0)
}

/// 启动失败必须说清原因: 双击没反应是最难排查的故障形态。
fn alert(title: &str, msg: &str) {
    #[cfg(target_os = "macos")]
    {
        let script = format!("display alert {:?} message {:?} as critical", title, msg);
        let _ = Command::new("osascript").args(["-e", &script]).spawn();
    }
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::ffi::OsStrExt;
        let title: Vec<u16> = std::ffi::OsStr::new(title)
            .encode_wide()
            .chain(Some(0))
            .collect();
        let msg: Vec<u16> = std::ffi::OsStr::new(msg)
            .encode_wide()
            .chain(Some(0))
            .collect();
        #[link(name = "user32")]
        extern "system" {
            fn MessageBoxW(
                hwnd: *mut std::ffi::c_void,
                text: *const u16,
                caption: *const u16,
                kind: u32,
            ) -> i32;
        }
        unsafe {
            MessageBoxW(std::ptr::null_mut(), msg.as_ptr(), title.as_ptr(), 0x10);
        }
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        eprintln!("{title}: {msg}");
    }
}

/// 拉起后端并回报它真正绑定的空闲端口(供开窗用)。
fn start_backend(resource_dir: Option<PathBuf>, settings_file: Option<PathBuf>) -> Result<u16, String> {
    let home = if cfg!(windows) {
        std::env::var_os("USERPROFILE").map(PathBuf::from)
    } else {
        std::env::var_os("HOME").map(PathBuf::from)
    }
    .unwrap_or_default();

    // 程序本体(app.py)所在目录，按优先级取第一个真实含 app.py 的：
    //   ① 热测试版编入的源码目录 ② .app 包内资源 ③ TINGDAO_HOME ④ ~/tingdao
    // 正式 App 始终优先自身 Resources/program，避免意外引用开发机文件。
    //
    // 坑(改前端时必踩): dev 下 ② 命中的是 target/debug/program(-windows)/ —— 那是 tauri-build
    // 在编译那一刻拷进去的快照, 优先级又压着 ③ TINGDAO_HOME。所以改完根目录的 index.html 只
    // `cp` 到 program-windows/ 是不够的, 必须再 cargo build 一次, 否则窗口里永远是旧页面。
    let app_dir = runtime_program_candidates(
        resource_dir.clone(),
        std::env::var("TINGDAO_HOME")
            .ok()
            .map(std::path::PathBuf::from),
        &home,
    )
    .into_iter()
    .find(|d| d.join("app.py").is_file())
    .ok_or_else(|| -> String {
        "找不到程序本体(app.py)。若从镜像安装，请确认「听道.app」完整拖入「应用程序」后再打开；\
             便携运行则用环境变量 TINGDAO_HOME 指向程序目录。"
            .to_string()
    })?;
    let app_py = app_dir.join("app.py");

    let py = find_python(
        resource_dir.as_deref(),
        settings_file.as_deref(),
        &home,
        cfg!(windows),
    )?;

    // 端口文件按壳的进程号命名, 多实例互不干扰; 起后端前先清同名残留, 免得读到上一轮的旧端口。
    let portfile = std::env::temp_dir().join(format!("tingdao.{}.port", std::process::id()));
    let _ = std::fs::remove_file(&portfile);
    *PORTFILE.lock().unwrap() = Some(portfile.clone());

    let mut command = Command::new(&py);
    command
        .arg(&app_py)
        .arg("--no-window")
        .env("TINGDAO_PORTFILE", &portfile)
        .current_dir(&app_dir)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    // Windows: python.exe 是「控制台子系统」的可执行文件, 而本壳是 GUI 子系统(见文件头
    // windows_subsystem = "windows")。GUI 进程去 spawn 控制台程序时, 系统会给孩子另开一个
    // 控制台窗口 —— 这就是「安装版每次启动都带一个黑终端」的成因, 跟没打包好无关。
    // CREATE_NO_WINDOW(0x08000000) 才是正解: 压根不给它分配控制台。
    // 别指望已有的 Stdio::null(): 它只接管管道, 窗口照样弹。
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    #[cfg(feature = "test-source")]
    {
        let contents = resource_dir.as_deref().and_then(Path::parent);
        let helper = contents
            .map(test_sck_helper_path)
            .filter(|path| path.is_file())
            .ok_or_else(|| "测试版缺少包内音频助手 tingdao-mix".to_string())?;
        command.env("TINGDAO_SCK_HELPER", helper);
        let mic_app = contents
            .map(test_mic_app_path)
            .filter(|path| path.is_dir())
            .ok_or_else(|| "测试版缺少包内麦克风助手 TingdaoMic.app".to_string())?;
        command.env("TINGDAO_MIC_APP", mic_app);
    }
    let child = command
        .spawn()
        .map_err(|e| format!("后端进程起不来：{e}"))?;
    *BACKEND.lock().unwrap() = Some(child);

    // 模型加载发生在 bind 之前(Engine 在模块导入期建), 所以要给足等待时间;
    // 模型没配齐时后端也会照常起, 到点录音才报「设置→本地模型」。
    // 第一步: 等后端把它真正绑到的空闲端口写进端口文件(拿到端口号)。
    let t0 = Instant::now();
    let port = loop {
        if let Some(p) = read_portfile(&portfile) {
            break p;
        }
        if t0.elapsed() > Duration::from_secs(READY_TIMEOUT_SECS) {
            stop_backend();
            return Err(format!(
                "后端 {READY_TIMEOUT_SECS} 秒内没就绪。\n可看日志 ~/Documents/transcripts/.tingdao.log"
            ));
        }
        std::thread::sleep(Duration::from_millis(150));
    };
    // 第二步: 端口号到手, 再确认服务真的能连上, 才交给窗口。
    let t1 = Instant::now();
    while !port_open(port) {
        if t1.elapsed() > Duration::from_secs(SERVE_TIMEOUT_SECS) {
            stop_backend();
            return Err(format!(
                "后端回报端口 {port} 但连不上服务。\n可看日志 ~/Documents/transcripts/.tingdao.log"
            ));
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    *BACKEND_PORT.lock().unwrap() = Some(port);
    Ok(port)
}

#[cfg(all(test, feature = "test-source"))]
mod tests {
    use super::test_source_dir;

    #[test]
    fn test_source_build_should_prefer_the_configured_source_directory() {
        assert_eq!(
            test_source_dir().to_string_lossy(),
            env!("TINGDAO_TEST_SOURCE_DIR")
        );
    }

    #[test]
    fn test_source_build_uses_embedded_mix_helper() {
        assert_eq!(
            super::test_sck_helper_path(std::path::Path::new("/Test.app/Contents")),
            std::path::Path::new("/Test.app/Contents/MacOS/tingdao-mix")
        );
    }

    #[test]
    fn test_source_build_uses_embedded_microphone_app() {
        assert_eq!(
            super::test_mic_app_path(std::path::Path::new("/Test.app/Contents")),
            std::path::Path::new("/Test.app/Contents/Resources/TingdaoMic.app")
        );
    }
}

#[cfg(test)]
mod release_tests {
    #[test]
    fn repository_new_window_allows_only_the_official_repository_url() {
        assert!(super::is_repository_url("https://github.com/Ayin-git1/tingdao"));
        assert!(super::is_repository_url("https://github.com/Ayin-git1/tingdao/"));
        assert!(!super::is_repository_url("https://github.com/Ayin-git1/other"));
        assert!(!super::is_repository_url("https://example.com"));
    }

    #[test]
    fn windows_python_default_uses_venv_scripts_directory() {
        let path = super::default_python_path(std::path::Path::new("C:/Users/Ayin"), true);
        assert!(path.ends_with(std::path::Path::new("tingdao-venv/Scripts/python.exe")));
    }

    #[test]
    fn bundled_program_directory_is_below_tauri_resource_directory() {
        // 包内程序目录名按平台分叉(mac 是 program/, Windows 是 stage_windows.js 生成的 program-windows/),
        // 断言得跟着 cfg 走 —— 写死 mac 值会让 Windows 上跑测试的人看到两条必红的假失败。
        let bundled = if cfg!(windows) { "program-windows" } else { "program" };
        assert_eq!(
            super::bundled_program_dir(std::path::Path::new("C:/Apps/Tingdao/resources")),
            std::path::PathBuf::from(format!("C:/Apps/Tingdao/resources/{bundled}"))
        );
    }

    #[test]
    fn bundled_program_resources_precede_developer_override() {
        let bundled = if cfg!(windows) { "program-windows" } else { "program" };
        let candidates = super::runtime_program_candidates(
            Some(std::path::PathBuf::from("/Bundle/Contents/Resources")),
            Some(std::path::PathBuf::from("/External/program")),
            std::path::Path::new("/User"),
        );
        assert_eq!(
            candidates,
            vec![
                std::path::PathBuf::from(format!("/Bundle/Contents/Resources/{bundled}")),
                std::path::PathBuf::from("/External/program"),
                std::path::PathBuf::from("/User/tingdao"),
            ]
        );
    }

    #[test]
    fn pick_ready_returns_the_first_ready_venv_and_reports_only_real_attempts() {
        // 三种落点: 压根没装(约定路径不存在) / 装了但缺依赖 / 齐活。
        // 断言的不只是「选中第三个」, 还有失败清单的口径 —— 只有真去过的第二个能进清单。
        let root = std::env::temp_dir().join("tingdao-shell-pickready");
        let missing = root.join("missing");
        let bare = root.join("bare");
        let ready = root.join("ready");
        std::fs::create_dir_all(&missing).unwrap();
        std::fs::create_dir_all(bare.join("Lib").join("site-packages")).unwrap();
        std::fs::create_dir_all(bare.join("Scripts")).unwrap();
        std::fs::write(bare.join("Scripts").join("python.exe"), b"").unwrap();
        std::fs::create_dir_all(ready.join("Lib").join("site-packages").join("torch")).unwrap();
        std::fs::create_dir_all(ready.join("Scripts")).unwrap();
        std::fs::write(ready.join("Scripts").join("python.exe"), b"").unwrap();

        let mut seen = Vec::new();
        let mut trail = Vec::new();
        let picked = super::pick_ready(
            vec![missing.clone(), bare.clone(), ready.clone()],
            true,
            &mut seen,
            &mut trail,
        );
        assert_eq!(picked, Some(ready.join("Scripts").join("python.exe")));
        assert_eq!(trail, vec![format!("  · {} —— 缺听道依赖", bare.join("Scripts").join("python.exe").display())]);

        // 去重: 同一批 venv 再来一遍(浅扫会重复撞见约定路径), 不该再产出第二条线索
        let before = trail.len();
        assert_eq!(
            super::pick_ready(vec![bare.clone(), ready.clone()], true, &mut seen, &mut trail),
            None
        );
        assert_eq!(trail.len(), before);
    }

    /// 依赖探测是「找到一个 python」与「找到一个能跑的 python」之间唯一的屏障, 拿真目录验。
    /// 两个用例都显式传 windows: true, 让 site-packages 的走法在非 Windows 机器上也稳定。
    #[test]
    fn dependency_probe_reads_site_packages_without_running_python() {
        let hit = std::env::temp_dir().join("tingdao-shell-pyprobe-hit");
        std::fs::create_dir_all(hit.join("Lib").join("site-packages").join("faster_whisper-1.1.0.dist-info"))
            .unwrap();
        assert!(super::has_tingdao_deps(&hit, true));

        let empty = std::env::temp_dir().join("tingdao-shell-pyprobe-empty");
        std::fs::create_dir_all(empty.join("Lib").join("site-packages")).unwrap();
        assert!(!super::has_tingdao_deps(&empty, true));
    }
}

fn stop_backend() {
    if let Some(mut c) = BACKEND.lock().unwrap().take() {
        if let Some(port) = *BACKEND_PORT.lock().unwrap() {
            request_shutdown(port);
        }
        let deadline = Instant::now() + Duration::from_secs(SHUTDOWN_TIMEOUT_SECS);
        loop {
            match c.try_wait() {
                Ok(Some(_)) => break,
                Err(_) => break,
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(100));
                }
                Ok(None) => {
                    let _ = c.kill();
                    break;
                }
            }
        }
        let _ = c.wait();
    }
    *BACKEND_PORT.lock().unwrap() = None;
    if let Some(pf) = PORTFILE.lock().unwrap().take() {
        let _ = std::fs::remove_file(pf);
    }
}

/// 明确告诉 DWM「边框外观我自己画」—— 见 open_main_window 的 Windows 分支。两件事一起办:
///   33 CORNER_PREFERENCE = DONOTROUND(1): Win11 的自动圆角半径与 CSS 的不重合, 两层弧叠加会在
///     角上露出深浅边; 更要紧的是它并不可靠 —— WebView2 的合成层被提升为硬件覆盖层(游戏画面、
///     动态壁纸前面)时掩码直接失效, 那正是「背景溢出窗口圆角」的老成因。掩码不可信, 就彻底不依赖。
///   34 BORDER_COLOR = COLOR_NONE(0): 去掉 Win11 给窗口描的那圈 1px 浅灰描边。窗口现在是透明的,
///     这条描边会按方角画, 正好盖在我们自绘的圆弧外面。
/// DWM 会在窗口被移动/贴靠/改 DPI 后重置这些属性(此前实测: 拖一下窗口, 系统又自作主张),
/// 所以除了建窗时设一次, 还得在 Moved/Resized 事件里反复摁回去(两次调用, 微秒级)。
#[cfg(target_os = "windows")]
fn apply_selfdrawn_frame(hwnd_raw: isize) {
    #[link(name = "dwmapi")]
    extern "system" {
        fn DwmSetWindowAttribute(
            hwnd: isize,
            attribute: u32,
            value: *const i32,
            size: u32,
        ) -> i32;
    }
    let no_round: i32 = 1; // DWMWCP_DONOTROUND
    let no_border: i32 = 0; // DWMWA_COLOR_NONE
    unsafe {
        DwmSetWindowAttribute(hwnd_raw, 33, &no_round, 4);
        DwmSetWindowAttribute(hwnd_raw, 34, &no_border, 4);
    }
}

/// 切换到非持久化 WebView 时，清除旧版默认数据存储；完成回调后才记迁移标记。
#[cfg(target_os = "macos")]
fn clear_legacy_webview_cache(app: &tauri::App, window: &tauri::WebviewWindow) {
    let Some(settings) = settings_file_path(app) else { return };
    let Some(data) = settings.parent() else { return };
    let marker = data.join(".webview-cache-migrated");
    if marker.exists() { return; }
    if let Err(error) = window.with_webview(move |_| {
        let Some(mtm) = objc2::MainThreadMarker::new() else { return };
        // 使用 WebKit 原生接口，避免猜测或直接删除系统管理的目录。
        unsafe {
            let store = objc2_web_kit::WKWebsiteDataStore::defaultDataStore(mtm);
            let types = objc2_web_kit::WKWebsiteDataStore::allWebsiteDataTypes(mtm);
            let date = objc2_foundation::NSDate::dateWithTimeIntervalSince1970(0.0);
            let done = block2::RcBlock::new(move || {
                if let Err(error) = std::fs::write(&marker, b"1") {
                    eprintln!("无法保存旧 WebView 缓存清理标记: {error}");
                }
            });
            store.removeDataOfTypes_modifiedSince_completionHandler(&types, &date, &done);
        }
    }) {
        eprintln!("旧 WebView 缓存清理失败: {error}");
    }
}

/// 用后端回报的端口, 在运行时把主窗口开起来。
/// 窗口的尺寸/居中等写在这里而非 tauri.conf.json —— 因为 URL 现在带的是动态端口, 只能建窗时注入。
fn open_main_window(app: &mut tauri::App, port: u16) -> tauri::Result<()> {
    let url_str = format!("http://127.0.0.1:{port}/");
    // External 变体的字段类型是 url::Url, 所以这里的 .parse() 会自动按该类型解析, 无需额外命名。
    // 我们自拼的地址必然合法, 真解析失败(理论不可达)就归成 InvalidUrl 让壳启动流程干净报错。
    let url = WebviewUrl::External(url_str.parse().map_err(tauri::Error::InvalidUrl)?);

    let mut builder = WebviewWindowBuilder::new(app, "main", url)
        // WKWebView 无法指定缓存目录，使用内存数据存储避免按动态端口积累磁盘缓存。
        .incognito(true)
        .title("听道")
        .inner_size(1000.0, 640.0)
        .min_inner_size(760.0, 520.0)
        .center()
        // 后端页面不带 Tauri 前端桥，target=_blank 的请求没人接会静默消失。
        // 这里只交给系统浏览器打开固定的仓库地址，其他新窗口一律拒绝。
        .on_new_window(|url, _| {
            open_repository_url(url.as_str());
            tauri::webview::NewWindowResponse::Deny
        });
    // 不透明白底只给 mac 用(压住 WKWebView 首帧白闪)。Windows 下面要走透明窗口,
    // 而 wry 在 transparent 时会忽略 background_color —— 干脆不设, 免得读代码时误判窗口底是白的。
    #[cfg(not(target_os = "windows"))]
    {
        builder = builder.background_color(Color(255, 255, 255, 255));
    }

    // 标题栏方案与旧配置一致: Overlay + 隐藏标题 + 红绿灯移到 (20,30), 只 macOS 有这几个 setter。
    #[cfg(target_os = "macos")]
    {
        builder = builder
            .title_bar_style(tauri::TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(tauri::LogicalPosition::new(20.0, 30.0));
    }

    // Windows 没有上面这套 setter(标题栏既不能透明也不能只藏图标), 要把网页拉到顶、
    // 去掉左上的图标与「听道」字样, 只能整条摘掉原生标题栏。窗口底子转由网页自绘:
    // 顶部拖拽 = .dragbar[data-tauri-drag-region], 右上角最小化/最大化/关闭 = index.html
    // 里的 .winctl(见其中 data-platform="windows" 那段)。
    //
    // 圆角同样由网页自绘(见 index.html 里 html[data-platform="windows"] 的 clip-path), 这里
    // 只负责把它需要的地基打好:
    //   transparent(true) —— 窗口必须有 alpha 通道, 否则 CSS 裁出来的四角会被不透明窗口底顶死。
    //     tao 建窗用的是 NULL 画刷(不自带底色), wry 会把 WebView2 的 DefaultBackgroundColor
    //     设成 (0,0,0,0), 两者合起来才让"四角外透出桌面"成立。
    //   shadow(false) —— 关键一步。shadow(true) 会留着 WS_THICKFRAME, tao 便在 WM_NCCALCSIZE 里
    //     按边框宽度内缩客户区(window.rs 的 MARKER_UNDECORATED_SHADOW 分支), 于是窗口矩形与客户区
    //     之间留下一条非客户区带: 它归 NULL 画刷管, 平时靠 DWM 的圆角掩码裁掉, 掩码一失效就露出
    //     一条黑边 —— 等于还是把外观押在掩码上。关掉 shadow, tao 走 WM_NCCALCSIZE 的 return 0
    //     分支, 客户区 == 窗口矩形, 那条带子从根上不存在, 圆角与边缘就只由 CSS 说了算。
    //     代价: 原生边缘缩放与 Win11 贴边吸附没了, 缩放改由网页边缘的 .wresize 条调
    //     plugin:window|start_resize_dragging 承担(见 index.html)。
    //   DWM 的圆角与描边显式关掉(apply_selfdrawn_frame): 既然窗口带 alpha, 让系统再自作主张
    //     画一层弧/一圈 1px 浅灰描边, 只会在角上叠出深浅边。
    //
    // 三键走 tauri 内建的 plugin:window|* 命令(capabilities/default.json 里已放行)。别改成壳里
    // 自注册的 #[tauri::command]: 主窗口加载的是后端直出的 http://127.0.0.1:<动态端口>, 属 remote
    // 页面, 自定义命令在这条路上会被 ACL 判 "not allowed. Plugin not found"。也别指望
    // withGlobalTauri —— 它靠 @tauri-apps/api 这个 npm 包产出全局脚本, 本仓库只装了 cli, 开了是静默无效。
    #[cfg(target_os = "windows")]
    {
        builder = builder.decorations(false).transparent(true).shadow(false);
    }

    let window = builder.build()?;
    #[cfg(target_os = "macos")]
    clear_legacy_webview_cache(app, &window);

    // 关掉 DWM 圆角, 让 CSS 成为唯一的圆角来源(理由见上)。拖动/贴靠后会被重置, 故
    // on_window_event 里还会再摁。
    #[cfg(target_os = "windows")]
    if let Ok(hwnd) = window.hwnd() {
        apply_selfdrawn_frame(hwnd.0 as isize);
    }

    Ok(())
}

fn main() {
    let mut builder = tauri::Builder::default();
    #[cfg(target_os = "macos")]
    {
        builder = builder.menu(app_menu).on_menu_event(move |_app, event| {
            if event.id() == MICROPHONE_MODES_MENU_ID {
                let result = BACKEND_PORT
                    .lock()
                    .unwrap()
                    .ok_or_else(|| "录音服务尚未启动".to_string())
                    .and_then(request_microphone_modes);
                if let Err(error) = result {
                    alert("无法打开麦克风模式", &error);
                }
            }
        });
    }
    let app = builder
        // macOS 默认"关最后一个窗口不退出", 对这个单窗口工具就是坑: 窗口没了、后端还在悄悄
        // 占着麦克风。这里把"关窗"直接等价于"退出", 退出再触发下面的 stop_backend。
        .on_window_event(|window, event| {
            match event {
                tauri::WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    window.app_handle().exit(0);
                }
                // 拖动/贴靠/改尺寸后 DWM 会重置圆角属性, 再摁一次(见 apply_selfdrawn_frame)
                #[cfg(target_os = "windows")]
                tauri::WindowEvent::Moved(_) | tauri::WindowEvent::Resized(_) => {
                    if let Ok(hwnd) = window.hwnd() {
                        apply_selfdrawn_frame(hwnd.0 as isize);
                    }
                }
                _ => {}
            }
        })
        // 主窗口在 setup 里建: 需要先有后端回报的动态端口才能定 URL, 而端口在 start_backend 已到手。
        .setup(move |app| {
            let resource_dir = app.path().resource_dir().ok();
            let settings_file = settings_file_path(app);
            let port = match start_backend(resource_dir, settings_file) {
                Ok(p) => p,
                Err(e) => {
                    // 坑: tauri 的 setup hook 返回 Err 时, 会在 run() 内部直接 panic(GUI 进程
                    // 无声无息退出 101, 用户什么都看不到), 下面 unwrap_or_else 的 alert 兜不到它。
                    // 所以启动失败必须在这里自己弹窗 + 退出, 让用户看到具体原因。
                    alert("听道启动失败", &e);
                    std::process::exit(1);
                }
            };
            if let Err(error) = open_main_window(app, port) {
                stop_backend();
                alert("听道启动失败", &error.to_string());
                std::process::exit(1);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .unwrap_or_else(|e| {
            alert("听道启动失败", &e.to_string());
            std::process::exit(1);
        });

    app.run(|_handle, event| {
        match event {
            tauri::RunEvent::ExitRequested { api, .. } => {
                if !confirm_recording_exit() {
                    api.prevent_exit();
                }
            },
            tauri::RunEvent::Exit { .. } => stop_backend(),
            _ => {}
        }
    });
}

#[cfg(test)]
mod recording_exit_tests {
    #[test]
    fn only_explicit_save_confirmation_exits() {
        assert!(super::exit_dialog_confirmed(true, "退出并保存\n"));
        for button in ["取消", "", "好"] {
            assert!(!super::exit_dialog_confirmed(true, button));
        }
        assert!(!super::exit_dialog_confirmed(false, "退出并保存"));
    }
    #[test]
    fn active_recording_and_pause_show_save_notice() {
        for state in ["recording", "paused"] {
            let response = format!("HTTP/1.1 200 OK\r\n\r\n{{\"state\":\"{state}\"}}");
            assert!(super::recording_exit_message(&response).unwrap().contains("退出后项目将自动保存"));
        }
    }
    #[test]
    fn idle_stopping_and_invalid_responses_do_not_show_notice() {
        for body in ["{\"state\":\"idle\"}", "{\"state\":\"stopping\"}", "{}", "invalid"] {
            assert_eq!(super::recording_exit_message(&format!("HTTP/1.1 200 OK\r\n\r\n{body}")), None);
        }
        assert_eq!(super::recording_exit_message(""), None);
    }
}
