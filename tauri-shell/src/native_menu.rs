//! macOS 菜单定义与页面状态同步。页面动作由同包 native_menu.js 复用。
use tauri::{
    menu::{CheckMenuItem, Menu, MenuItem, MenuItemKind, PredefinedMenuItem, Submenu},
    AppHandle, Runtime,
};

pub const SCRIPT: &str = include_str!("native_menu.js");

fn item<R: Runtime>(
    app: &AppHandle<R>,
    id: &str,
    text: &str,
    key: Option<&str>,
) -> tauri::Result<MenuItem<R>> {
    MenuItem::with_id(app, format!("native-{id}"), text, false, key)
}
fn check<R: Runtime>(app: &AppHandle<R>, id: &str, text: &str) -> tauri::Result<CheckMenuItem<R>> {
    CheckMenuItem::with_id(
        app,
        format!("native-{id}"),
        text,
        false,
        false,
        None::<&str>,
    )
}

pub fn build<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
    let app_menu = Submenu::with_items(
        app,
        "听道",
        true,
        &[
            &item(app, "about", "关于听道", None)?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "settings", "设置…", Some("CmdOrCtrl+,"))?,
            &item(app, "update", "检查更新…", None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::services(app, Some("服务"))?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::hide(app, Some("隐藏听道"))?,
            &PredefinedMenuItem::hide_others(app, Some("隐藏其他"))?,
            &PredefinedMenuItem::show_all(app, Some("显示全部"))?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::quit(app, Some("退出听道"))?,
        ],
    )?;
    let groups = Submenu::with_items(
        app,
        "移到分组",
        true,
        &[
            &item(app, "group-choose", "选择分组…", None)?,
            &item(app, "group-remove", "移出分组", None)?,
        ],
    )?;
    let export = Submenu::with_items(
        app,
        "导出",
        true,
        &[
            &item(app, "export-bundle", "导出完整笔记…", None)?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "copy-md", "复制 Markdown 文件", None)?,
            &item(app, "copy-plain", "复制纯文本", Some("CmdOrCtrl+E"))?,
        ],
    )?;
    let file = Submenu::with_items(
        app,
        "文件",
        true,
        &[
            &item(app, "import-media", "导入音频 / 视频…", None)?,
            &item(app, "import-note", "导入完整笔记…", None)?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "rename", "重命名项目…", None)?,
            &item(app, "favorite", "收藏", None)?,
            &groups,
            &PredefinedMenuItem::separator(app)?,
            &export,
            &item(app, "reveal", "在 Finder 中显示项目", None)?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "archive", "归档项目", None)?,
        ],
    )?;
    let processing = Submenu::with_items(
        app,
        "文稿处理",
        true,
        &[
            &item(app, "cloud-transcribe", "云端转写…", None)?,
            &item(app, "cloud-refine", "修正错字…", None)?,
            &item(app, "summary", "生成摘要目录…", None)?,
            &item(app, "silence", "跳过静音重新识别…", None)?,
        ],
    )?;
    let edit = Submenu::with_items(
        app,
        "编辑",
        true,
        &[
            &PredefinedMenuItem::undo(app, Some("撤销"))?,
            &PredefinedMenuItem::redo(app, Some("重做"))?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::cut(app, Some("剪切"))?,
            &PredefinedMenuItem::copy(app, Some("拷贝"))?,
            &PredefinedMenuItem::paste(app, Some("粘贴"))?,
            &PredefinedMenuItem::select_all(app, Some("全选"))?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "search", "搜索项目或分组…", Some("CmdOrCtrl+K"))?,
            &item(app, "find", "查找文稿…", Some("CmdOrCtrl+F"))?,
            &item(app, "replace", "替换…", None)?,
            &PredefinedMenuItem::separator(app)?,
            &processing,
        ],
    )?;
    let display = Submenu::with_items(
        app,
        "显示",
        true,
        &[
            &item(app, "home", "返回主页", None)?,
            &item(app, "show-favorites", "查看收藏", None)?,
            &item(app, "show-archive", "查看归档", None)?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "sidebar", "隐藏项目栏", Some("CmdOrCtrl+B"))?,
            &item(app, "drawer", "显示课后笔记", Some("CmdOrCtrl+Shift+B"))?,
            &item(app, "all-notes", "全部笔记", None)?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "music", "配乐播放器", None)?,
            &item(app, "review", "复习打卡", None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::fullscreen(app, Some("进入 / 退出全屏"))?,
        ],
    )?;
    let sources = Submenu::with_items(
        app,
        "录音来源",
        true,
        &[
            &check(app, "source-system", "仅系统声音")?,
            &check(app, "source-mic", "仅麦克风")?,
            &check(app, "source-mix", "系统声音和麦克风")?,
        ],
    )?;
    // 麦克风模式仍走壳到后端的原有请求。
    let mic = MenuItem::with_id(
        app,
        super::MICROPHONE_MODES_MENU_ID,
        "麦克风模式…",
        false,
        None::<&str>,
    )?;
    let record = Submenu::with_items(
        app,
        "录音",
        true,
        &[
            &item(app, "record-start", "开始录音", Some("CmdOrCtrl+Shift+R"))?,
            &item(app, "record-pause", "暂停录音", None)?,
            &item(app, "record-stop", "结束并保存…", None)?,
            &PredefinedMenuItem::separator(app)?,
            &sources,
            &mic,
            &item(app, "hotwords", "热词库…", None)?,
        ],
    )?;
    let rates = Submenu::with_items(
        app,
        "播放速度",
        true,
        &[
            &check(app, "rate-0", "0.75 倍")?,
            &check(app, "rate-1", "1 倍")?,
            &check(app, "rate-2", "1.25 倍")?,
            &check(app, "rate-3", "1.5 倍")?,
            &check(app, "rate-4", "2 倍")?,
        ],
    )?;
    // 空格、方向键由页面按输入焦点处理，避免系统菜单抢走文字编辑按键。
    let play = Submenu::with_items(
        app,
        "播放",
        true,
        &[
            &item(app, "play", "播放", None)?,
            &item(app, "previous", "上一句", None)?,
            &item(app, "next", "下一句", None)?,
            &PredefinedMenuItem::separator(app)?,
            &rates,
        ],
    )?;
    let notes = Submenu::with_items(
        app,
        "笔记",
        true,
        &[
            &item(app, "note-add", "添加时间线笔记", Some("CmdOrCtrl+N"))?,
            &item(
                app,
                "note-photo",
                "用 iPhone 拍照插入",
                Some("CmdOrCtrl+Shift+P"),
            )?,
            &PredefinedMenuItem::separator(app)?,
            &item(app, "note-generate", "生成课后笔记…", None)?,
            &item(app, "note-regenerate", "重新生成课后笔记…", None)?,
            &item(app, "note-copy", "复制课后笔记", None)?,
        ],
    )?;
    let window = Submenu::with_items(
        app,
        "窗口",
        true,
        &[
            &PredefinedMenuItem::minimize(app, Some("最小化"))?,
            &PredefinedMenuItem::maximize(app, Some("缩放"))?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::bring_all_to_front(app, Some("将所有窗口前置"))?,
        ],
    )?;
    let help = Submenu::with_items(
        app,
        "帮助",
        true,
        &[
            &item(app, "keys", "键盘快捷键", Some("CmdOrCtrl+/"))?,
            &MenuItem::with_id(app, "native-repository", "项目主页", true, None::<&str>)?,
        ],
    )?;
    Menu::with_items(
        app,
        &[
            &app_menu, &file, &edit, &display, &record, &play, &notes, &window, &help,
        ],
    )
}

// get() 只查一层；遍历子菜单同步。只接受已存在的项目，不执行页面传来的代码。
pub fn apply_state<R: Runtime>(app: &AppHandle<R>, state: &serde_json::Value) {
    fn apply<R: Runtime>(items: Vec<MenuItemKind<R>>, state: &serde_json::Value) {
        for item in items {
            if let MenuItemKind::Submenu(menu) = item {
                apply(menu.items().unwrap_or_default(), state);
                continue;
            }
            let id = item.id().as_ref();
            let key = id.strip_prefix("native-").unwrap_or(id);
            let Some(value) = state.get(key) else {
                continue;
            };
            let enabled = value["enabled"].as_bool().unwrap_or(false);
            match item {
                MenuItemKind::MenuItem(item) => {
                    let _ = item.set_enabled(enabled);
                    if let Some(text) = value["text"].as_str() {
                        let _ = item.set_text(text);
                    }
                    if let Some(key) = value["accelerator"].as_str() {
                        let _ = item.set_accelerator(Some(key));
                    }
                }
                MenuItemKind::Check(item) => {
                    let _ = item.set_enabled(enabled);
                    let _ = item.set_checked(value["checked"].as_bool().unwrap_or(false));
                }
                _ => {}
            }
        }
    }
    if let Some(menu) = app.menu() {
        apply(menu.items().unwrap_or_default(), state);
    }
}
