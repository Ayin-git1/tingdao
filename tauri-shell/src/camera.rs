//! 连续互通相机: 录音中点相机钮 → 弹出系统的「iPhone › 拍照 / 扫描文稿 / 添加速绘」→ 拍完, 照片回到网页。
//!
//! 实测(macOS 27)两条硬约束, 别"简化"回去:
//! 1. 系统只把这项服务交给 NSTextView。自定义 NSView 即便实现 validRequestorForSendType:returnType:
//!    并登记图片类型, 系统也从不来问, 菜单项一直灰着。所以接收者是一枚隐形的 NSTextView 子类,
//!    只重写 readSelectionFromPasteboard: 把照片截走(不让它真插进文本框)。
//! 2. iPhone 那组菜单项只在"走正常右键流程"时由 AppKit 补进来: 把合成的右键事件交给视图的
//!    rightMouseDown:, 视图的 menuForEvent: 只给标题行即可。NSMenu popUpContextMenu / popUpMenuPositioningItem
//!    直接弹的菜单不会补, 只剩自己加的项。
//!
//! 3. 补进来的「自动填充」「扫描文稿」「添加速绘」用不上, 在 AppKit 加项时(NSMenuDidAddItemNotification)
//!    逐个藏掉, 只留每台设备的「拍照」。自己那行标题也藏起来, 但不能不加: 空菜单 AppKit 不往里补。
//! 4. 快捷键要"直接拍": 菜单照样走一遍(不走就没有拍照项), 等 AppKit 补进第一台设备的「拍照」,
//!    投到菜单跟踪循环里收起菜单、替用户点下它。之后的会话与手点完全一样。
//!
//! 网页 → 壳: 隐藏 iframe 导航到 tingdao-camera://take?x=&y=(见 main.rs 的 on_navigation)。
//! 自定义 #[tauri::command] 对后端直出的 remote 页面不可用, 理由同 main.rs 里窗口三键那段。
//! 壳 → 网页: tauri 事件 CAMERA_STATE_EVENT / CAMERA_PHOTO_EVENT, 网页用 plugin:event|listen 收。

use std::cell::{Cell, RefCell};
use std::ptr::NonNull;
use std::sync::OnceLock;

use base64::Engine;
use block2::RcBlock;
use objc2::rc::Retained;
use objc2::{define_class, msg_send, sel, MainThreadMarker, MainThreadOnly};
use objc2_app_kit::{
    NSBitmapImageFileType, NSBitmapImageRep, NSColor, NSEvent, NSEventModifierFlags, NSEventType, NSMenu,
    NSMenuDidAddItemNotification, NSMenuWillSendActionNotification, NSMenuItem, NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeTIFF,
    NSEventTrackingRunLoopMode, NSModalPanelRunLoopMode, NSResponder, NSText, NSTextView, NSView, NSWindow,
};
use objc2_foundation::{
    NSArray, NSDefaultRunLoopMode, NSDictionary, NSNotification, NSNotificationCenter, NSObject, NSPoint, NSRect, NSRunLoop,
    NSSize, NSString,
};
use tauri::Emitter;

pub const CAMERA_SCHEME: &str = "tingdao-camera";
/// { waiting: bool } —— 点了菜单项报 true; 菜单关闭或连续互通会话结束(拍完/取消/失败)报 false。
const CAMERA_STATE_EVENT: &str = "tingdao://camera-state";
/// { mime, data(base64) } —— iPhone 拍完的照片。
const CAMERA_PHOTO_EVENT: &str = "tingdao://camera-photo";

pub static APP: OnceLock<tauri::AppHandle> = OnceLock::new();

thread_local! {
    /// 当前挂着的接收视图与弹菜单前的第一响应者(一般是 WKWebView), 只在主线程碰。
    static ACTIVE: RefCell<Option<(Retained<CameraView>, Option<Retained<NSResponder>>)>> = const { RefCell::new(None) };
    /// 刚摘下的视图多留一轮: finish() 可能正在它自己的 readSelectionFromPasteboard: 里执行, 不能当场释放。
    static RETIRED: RefCell<Option<Retained<CameraView>>> = const { RefCell::new(None) };
    /// 这次是快捷键发起的: 等「拍照」一出现就替用户点下, 点过即清。
    static DIRECT: Cell<bool> = const { Cell::new(false) };
}

pub fn init(app: tauri::AppHandle) {
    let _ = APP.set(app);
}

fn emit(event: &str, payload: serde_json::Value) {
    if let Some(app) = APP.get() {
        let _ = app.emit(event, payload);
    }
}

define_class!(
    #[unsafe(super(NSTextView, NSText, NSView, NSResponder, NSObject))]
    #[thread_kind = MainThreadOnly]
    #[name = "TingdaoContinuityCameraView"]
    struct CameraView;

    impl CameraView {
        // 右键菜单只放一行藏起来的占位; AppKit 会在下面补上 iPhone 名称与拍照等项(以及系统自带的「自动填充」)。
        #[unsafe(method_id(menuForEvent:))]
        fn menu_for_event(&self, _event: &NSEvent) -> Option<Retained<NSMenu>> {
            let mtm = self.mtm();
            let menu = NSMenu::new(mtm);
            let placeholder = NSMenuItem::new(mtm);
            placeholder.setHidden(true);
            menu.addItem(&placeholder);
            Some(menu)
        }

        #[unsafe(method(readSelectionFromPasteboard:))]
        fn read_selection(&self, pasteboard: &NSPasteboard) -> bool {
            let photo = read_photo(pasteboard);
            if let Some((mime, bytes)) = photo {
                let data = base64::engine::general_purpose::STANDARD.encode(bytes);
                emit(CAMERA_PHOTO_EVENT, serde_json::json!({ "mime": mime, "data": data }));
            } else {
                emit(CAMERA_STATE_EVENT, serde_json::json!({ "waiting": false }));
            }
            finish();
            true // 已处理: 不让文本框自己把图片插进去
        }
    }
);

/// iPhone 一般直接给 JPEG; 只拿到 TIFF 时转成 JPEG, 免得几十 MB 的位图塞进笔记。
fn read_photo(pasteboard: &NSPasteboard) -> Option<(&'static str, Vec<u8>)> {
    if let Some(data) = pasteboard.dataForType(&NSString::from_str("public.jpeg")) {
        return Some(("image/jpeg", data.to_vec()));
    }
    if let Some(data) = pasteboard.dataForType(unsafe { NSPasteboardTypePNG }) {
        return Some(("image/png", data.to_vec()));
    }
    // HEIC / TIFF 统一转 JPEG: 网页未必解得了 HEIC, TIFF 又太大
    let raw = ["public.heic", "public.heif"]
        .iter()
        .find_map(|kind| pasteboard.dataForType(&NSString::from_str(kind)))
        .or_else(|| pasteboard.dataForType(unsafe { NSPasteboardTypeTIFF }))?;
    let rep = NSBitmapImageRep::imageRepWithData(&raw)?;
    let jpeg = unsafe { rep.representationUsingType_properties(NSBitmapImageFileType::JPEG, &NSDictionary::new()) }?;
    Some(("image/jpeg", jpeg.to_vec()))
}

/// AppKit 每往菜单加一项就过一遍: 只留紧跟在设备名后面的第一项(拍照), 其余(含设备名、分隔线)都藏掉。
/// 判断用 action 不用标题, 免得跟系统语言走。
fn keep_only_take_photo(notification: &NSNotification) {
    let Some(menu) = notification.object() else { return };
    let Ok(menu) = menu.downcast::<NSMenu>() else { return };
    let Some(info) = notification.userInfo() else { return };
    let Some(index) = info.objectForKey(&*NSString::from_str("NSMenuItemIndex")) else { return };
    let index: isize = unsafe { msg_send![&*index, integerValue] };
    let Some(item) = menu.itemAtIndex(index) else { return };
    let after_device = index > 0
        && menu.itemAtIndex(index - 1).and_then(|prev| prev.action()) == Some(sel!(_importFromDeviceText:));
    let take_photo = item.action() == Some(sel!(importFromDevice:)) && after_device;
    if !take_photo {
        item.setHidden(true);
        return;
    }
    // 中间那份临时菜单里的项还没挂上 representedObject, 点它没用; 要等真正显示的那份。
    if item.representedObject().is_none() || !DIRECT.with(|direct| direct.replace(false)) {
        return;
    }
    // 此刻 AppKit 还在往菜单里加项, 当场点会打乱它; 投到菜单跟踪循环的下一轮再点。
    let block = RcBlock::new(move || {
        menu.cancelTracking();
        menu.performActionForItemAtIndex(index);
    });
    unsafe {
        let modes = NSArray::from_slice(&[NSEventTrackingRunLoopMode, NSDefaultRunLoopMode, NSModalPanelRunLoopMode]);
        NSRunLoop::mainRunLoop().performInModes_block(&modes, &block);
    }
}

/// 摘下接收视图, 焦点还给弹菜单前的响应者(网页), 否则键盘快捷键会一直落空。
fn finish() {
    let Some((view, previous)) = ACTIVE.with(|active| active.borrow_mut().take()) else { return };
    if let Some(window) = view.window() {
        window.makeFirstResponder(previous.as_deref());
    }
    view.removeFromSuperview();
    RETIRED.with(|retired| *retired.borrow_mut() = Some(view));
}

/// 解析 tingdao-camera://take?x=&y=[&direct=1], 坐标是相机钮中心的网页 CSS 像素; direct=1 跳过菜单直接拍。
pub fn parse_request(url: &tauri::Url) -> Option<(f64, f64, bool)> {
    if url.scheme() != CAMERA_SCHEME || url.host_str() != Some("take") {
        return None;
    }
    let mut x = None;
    let mut y = None;
    let mut direct = false;
    for (key, value) in url.query_pairs() {
        match &*key {
            "x" => x = value.parse().ok(),
            "y" => y = value.parse().ok(),
            "direct" => direct = value == "1",
            _ => {}
        }
    }
    Some((x?, y?, direct))
}

/// 在 WKWebView 上(x, y)处弹出连续互通相机菜单。须在主线程调用。
///
/// # Safety
/// `webview` 与 `window` 必须是同一主窗口的 WKWebView 与 NSWindow。
pub unsafe fn present(webview: *mut std::ffi::c_void, window: *mut std::ffi::c_void, x: f64, y: f64, direct: bool) {
    let Some(mtm) = MainThreadMarker::new() else { return };
    let webview: &NSView = &*webview.cast();
    let window: &NSWindow = &*window.cast();
    finish(); // 上一次没等到照片(在 iPhone 上取消了)就再点: 先收掉旧的
    DIRECT.with(|flag| flag.set(direct));

    // WKWebView 是翻转坐标(原点左上), 与 CSS 一致; 万一不是, 按高度翻一下。
    let y = if webview.isFlipped() { y } else { webview.bounds().size.height - y };
    let frame = NSRect::new(NSPoint::new(x - 1.0, y - 1.0), NSSize::new(2.0, 2.0));
    let view: Retained<CameraView> = msg_send![CameraView::alloc(mtm), initWithFrame: frame];
    view.setRichText(true);
    view.setImportsGraphics(true);
    view.setDrawsBackground(false);
    view.setInsertionPointColor(Some(&NSColor::clearColor())); // 当第一响应者时别在按钮上闪一根光标
    webview.addSubview(&view);
    let previous = window.firstResponder();
    window.makeFirstResponder(Some(&view));
    ACTIVE.with(|active| *active.borrow_mut() = Some((view.clone(), previous)));

    let location = view.convertPoint_toView(NSPoint::new(1.0, 1.0), None);
    let Some(event) = NSEvent::mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure(
        NSEventType::RightMouseDown, location, NSEventModifierFlags::empty(), 0.0, window.windowNumber(), None, 0, 1, 1.0,
    ) else {
        finish();
        return;
    };
    // 实测: 选了「拍照」后整个连续互通会话(等 iPhone 拍照/取消)都在这次 rightMouseDown: 里跑完,
    // 照片也是在里面经 readSelectionFromPasteboard: 送达的。所以"进入等待"要在用户点菜单项那一刻
    // (WillSend, 动作发出之前)就报, 调用返回即会话结束: 不管照片到没到, 一律收起等待态。
    let center = NSNotificationCenter::defaultCenter();
    let block = RcBlock::new(|_: NonNull<NSNotification>| emit(CAMERA_STATE_EVENT, serde_json::json!({ "waiting": true })));
    let observer = center.addObserverForName_object_queue_usingBlock(Some(NSMenuWillSendActionNotification), None, None, &block);
    let trim = RcBlock::new(|note: NonNull<NSNotification>| keep_only_take_photo(note.as_ref()));
    let trimmer = center.addObserverForName_object_queue_usingBlock(Some(NSMenuDidAddItemNotification), None, None, &trim);
    let _: () = msg_send![&*view, rightMouseDown: &*event];
    center.removeObserver(trimmer.as_ref());
    DIRECT.with(|flag| flag.set(false)); // 没有可用的 iPhone 时根本等不到「拍照」, 别留到下次
    center.removeObserver(observer.as_ref());
    emit(CAMERA_STATE_EVENT, serde_json::json!({ "waiting": false }));
    finish(); // 照片已到时 readSelection 里已收过, 这里是空操作
}
