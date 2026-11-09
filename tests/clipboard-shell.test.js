const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync('tauri-shell/src/native_menu.rs', 'utf8');
const includes = pattern => assert.ok(pattern.test(source), `missing native clipboard menu wiring: ${pattern}`);

test('macOS shell keeps the native Edit menu for contenteditable clipboard shortcuts', () => {
  includes(/Submenu::with_items\(\s*app,\s*"编辑"/);
  includes(/PredefinedMenuItem::undo\(app, Some\("撤销"\)\)/);
  includes(/PredefinedMenuItem::redo\(app, Some\("重做"\)\)/);
  includes(/PredefinedMenuItem::cut\(app, Some\("剪切"\)\)/);
  includes(/PredefinedMenuItem::copy\(app, Some\("拷贝"\)\)/);
  includes(/PredefinedMenuItem::paste\(app, Some\("粘贴"\)\)/);
  includes(/PredefinedMenuItem::select_all\(app, Some\("全选"\)\)/);
});
