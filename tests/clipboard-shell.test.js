const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync('tauri-shell/src/main.rs', 'utf8');
const includes = pattern => assert.ok(pattern.test(source), `missing native clipboard menu wiring: ${pattern}`);

test('macOS shell keeps the native Edit menu for contenteditable clipboard shortcuts', () => {
  includes(/Submenu::with_items\(\s*app,\s*"编辑"/);
  includes(/PredefinedMenuItem::undo\(app, None\)/);
  includes(/PredefinedMenuItem::redo\(app, None\)/);
  includes(/PredefinedMenuItem::cut\(app, None\)/);
  includes(/PredefinedMenuItem::copy\(app, None\)/);
  includes(/PredefinedMenuItem::paste\(app, None\)/);
  includes(/PredefinedMenuItem::select_all\(app, None\)/);
});
