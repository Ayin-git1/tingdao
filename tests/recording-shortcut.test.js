const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

function shortcutHandler(platform = 'Darwin') {
  const html = fs.readFileSync('index.html', 'utf8');
  const marker = "document.addEventListener('keydown', e=>{";
  const start = html.indexOf(marker, html.indexOf('/* ---- 键盘快捷键 ----'));
  let depth = 0;
  let end = -1;
  for (let i = start + marker.length - 1; i < html.length; i++) {
    if (html[i] === '{') depth++;
    if (html[i] === '}' && --depth === 0) {
      end = i + 2;
      break;
    }
  }
  assert.notEqual(start, -1, '快捷键监听器应存在');
  assert.notEqual(end, -1, '快捷键监听器应完整');

  let handler;
  global.document = { addEventListener: (_type, fn) => { handler = fn; } };
  global.$ = id => ({
    keymodal: { classList: { contains: () => false } },
    fab: { click: () => { global.started = true; } },
    btnSide: { click: () => { global.sidebarToggled = true; } },
    btnNoteTop: { click: () => { global.drawerToggled = true; } },
  })[id];
  global.state = 'idle';
  global.view = null;
  global.hostPlatform = platform;
  global.recordStartShortcut = {key: 'r', shift: true};
  global.player = { src: '', paused: true };
  global.typingHere = () => false;
  global.openKeyCard = () => {};
  global.closeKeyCard = () => {};
  global.toast = () => {};
  global.eval(html.slice(start, end));
  return handler;
}

test('Command-Shift-R starts recording when idle', () => {
  global.started = false;
  const handler = shortcutHandler();
  let prevented = false;

  handler({
    key: 'r', code: 'KeyR', metaKey: true, ctrlKey: false, shiftKey: true,
    altKey: false, preventDefault: () => { prevented = true; },
  });

  assert.equal(global.started, true);
  assert.equal(prevented, true);
});

test('Ctrl-Shift-R starts recording on Windows when idle', () => {
  global.started = false;
  const handler = shortcutHandler('Windows');
  let prevented = false;

  handler({
    key: 'r', code: 'KeyR', metaKey: false, ctrlKey: true, shiftKey: true,
    altKey: false, preventDefault: () => { prevented = true; },
  });

  assert.equal(global.started, true);
  assert.equal(prevented, true);
});

test('Command-B reuses the left sidebar toggle', () => {
  global.sidebarToggled = false;
  const handler = shortcutHandler();
  let prevented = false;

  handler({
    key: 'b', code: 'KeyB', metaKey: true, ctrlKey: false, shiftKey: false,
    altKey: false, preventDefault: () => { prevented = true; },
  });

  assert.equal(global.sidebarToggled, true);
  assert.equal(prevented, true);
});

test('Command-Shift-B reuses the right drawer toggle', () => {
  global.drawerToggled = false;
  const handler = shortcutHandler();
  let prevented = false;

  handler({
    key: 'B', code: 'KeyB', metaKey: true, ctrlKey: false, shiftKey: true,
    altKey: false, preventDefault: () => { prevented = true; },
  });

  assert.equal(global.drawerToggled, true);
  assert.equal(prevented, true);
});
