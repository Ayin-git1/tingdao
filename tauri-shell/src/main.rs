#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

// 听道 tauri 壳: 窗口底子 + 后端进程归属方。
// 职责: 起 python 后端(headless) → 读它回报的空闲端口 → 按该端口开窗; 窗口退出时收掉后端, 不留孤儿进程。
// 后端/解释器路径读环境变量, 缺省回落到通用约定路径 —— 换机器改环境变量即可, 不必重编。
// 端口不再写死: 后端向 OS 现取一个真正空闲的回环端口, 再经壳指定的临时端口文件回报过来,
// 从根上避免「默认端口被别的程序占了就起不来 / 抢不到端口显示空白窗」。

use std::fs::File;
use std::io::Read;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};
use tauri::{utils::config::Color, Manager, WebviewUrl, WebviewWindowBuilder};

const READY_TIMEOUT_SECS: u64 = 60;
const SERVE_TIMEOUT_SECS: u64 = 10;

// 只有本进程亲手拉起的那份后端才归我们关; 端口文件也只由本进程创建、退出时清掉。
static BACKEND: LazyLock<Mutex<Option<Child>>> = LazyLock::new(|| Mutex::new(None));
static PORTFILE: LazyLock<Mutex<Option<PathBuf>>> = LazyLock::new(|| Mutex::new(None));

fn env_or(key: &str, fallback: String) -> String {
    std::env::var(key).unwrap_or(fallback)
}

/// .app 包内的资源根目录 Contents（可执行文件在 Contents/MacOS/tingdao-shell，向上两级）。
/// 非打包运行(cargo run)时该目录不含 program，候选会自动跳过, 回落到环境变量 / ~/tingdao。
fn bundle_contents_dir() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;      // .../Contents/MacOS/tingdao-shell
    let contents = exe.parent()?.parent()?;        // .../Contents
    Some(contents.to_path_buf())
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

fn port_open(port: u16) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
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
    #[cfg(not(target_os = "macos"))]
    {
        eprintln!("{title}: {msg}");
    }
}

/// 拉起后端并回报它真正绑定的空闲端口(供开窗用)。
fn start_backend() -> Result<u16, String> {
    let home = std::env::var("HOME").unwrap_or_default();

    // 程序本体(app.py)所在目录，按优先级取第一个真实含 app.py 的：
    //   ① 热测试版编入的源码目录 ② TINGDAO_HOME ③ .app 包内资源 ④ ~/tingdao
    let mut prog_candidates: Vec<std::path::PathBuf> = Vec::new();
    #[cfg(feature = "test-source")]
    prog_candidates.push(test_source_dir());
    if let Ok(h) = std::env::var("TINGDAO_HOME") {
        prog_candidates.push(std::path::PathBuf::from(h));
    }
    if let Some(c) = bundle_contents_dir() {
        prog_candidates.push(c.join("Resources").join("program"));
        prog_candidates.push(c.join("Resources"));
    }
    prog_candidates.push(std::path::PathBuf::from(format!("{home}/tingdao")));
    let app_dir = prog_candidates
        .into_iter()
        .find(|d| d.join("app.py").is_file())
        .ok_or_else(|| -> String {
            "找不到程序本体(app.py)。若从镜像安装，请确认「听道.app」完整拖入「应用程序」后再打开；\
             便携运行则用环境变量 TINGDAO_HOME 指向程序目录。"
                .to_string()
        })?;
    let app_py = app_dir.join("app.py");

    let py = env_or("TINGDAO_PY", format!("{home}/tingdao-venv/bin/python"));

    if !Path::new(&py).is_file() {
        return Err(format!(
            "找不到 Python 环境：{py}\n请先按引导创建虚拟环境并装好依赖，或用环境变量 TINGDAO_PY 指向你的解释器。"
        ));
    }

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
    #[cfg(feature = "test-source")]
    {
        let helper = bundle_contents_dir()
            .map(|contents| test_sck_helper_path(&contents))
            .filter(|path| path.is_file())
            .ok_or_else(|| "测试版缺少包内音频助手 tingdao-mix".to_string())?;
        command.env("TINGDAO_SCK_HELPER", helper);
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
    Ok(port)
}

#[cfg(all(test, feature = "test-source"))]
mod tests {
    use super::test_source_dir;

    #[test]
    fn test_source_build_should_prefer_the_configured_source_directory() {
        assert_eq!(test_source_dir().to_string_lossy(), env!("TINGDAO_TEST_SOURCE_DIR"));
    }

    #[test]
    fn test_source_build_uses_embedded_mix_helper() {
        assert_eq!(
            super::test_sck_helper_path(std::path::Path::new("/Test.app/Contents")),
            std::path::Path::new("/Test.app/Contents/MacOS/tingdao-mix")
        );
    }
}

fn stop_backend() {
    if let Some(mut c) = BACKEND.lock().unwrap().take() {
        // kill 发 SIGTERM; 后端 headless 分支收到后走与关窗同一套收尾(录音中会落盘)
        let _ = c.kill();
        let _ = c.wait();
    }
    if let Some(pf) = PORTFILE.lock().unwrap().take() {
        let _ = std::fs::remove_file(pf);
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
        .title("听道")
        .inner_size(1000.0, 640.0)
        .min_inner_size(760.0, 520.0)
        .center()
        .background_color(Color(255, 255, 255, 255));

    // 标题栏方案与旧配置一致: Overlay + 隐藏标题 + 红绿灯移到 (20,30), 只 macOS 有这几个 setter。
    #[cfg(target_os = "macos")]
    {
        builder = builder
            .title_bar_style(tauri::TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(tauri::LogicalPosition::new(20.0, 30.0));
    }

    builder.build()?;
    Ok(())
}

fn main() {
    let port = match start_backend() {
        Ok(p) => p,
        Err(e) => {
            alert("听道启动失败", &e);
            std::process::exit(1);
        }
    };

    let app = tauri::Builder::default()
        // macOS 默认"关最后一个窗口不退出", 对这个单窗口工具就是坑: 窗口没了、后端还在悄悄
        // 占着麦克风。这里把"关窗"直接等价于"退出", 退出再触发下面的 stop_backend。
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                window.app_handle().exit(0);
            }
        })
        // 主窗口在 setup 里建: 需要先有后端回报的动态端口才能定 URL, 而端口在 start_backend 已到手。
        .setup(move |app| {
            open_main_window(app, port)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("听道壳启动失败");

    app.run(|_handle, event| {
        if let tauri::RunEvent::Exit { .. } = event {
            stop_backend();
        }
    });
}
