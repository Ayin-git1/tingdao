const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

test('frontend uses backend platform to render Windows shortcut hints', () => {
  assert.equal(/function syncPlatformUI\(platform\)/.test(html), true, 'platform renderer exists');
  assert.equal(html.includes('data-platform="windows"'), true, 'Windows platform styling exists');
  assert.equal(html.includes('Ctrl+Shift+R'), true, 'Windows shortcut labels use Ctrl');
  assert.equal(html.includes('syncPlatformUI(d.platform)'), true, 'status platform reaches the renderer');
});

test('Windows chrome leaves space for native right-side window controls', () => {
  assert.equal(html.includes('html[data-platform="windows"] .topbar'), true);
  assert.equal(html.includes('html[data-platform="windows"] .hang'), true);
});

test('Windows help text no longer claims its appearance follows macOS', () => {
  assert.equal(html.includes('跟随 Windows 外观自动切换。'), true);
});

test('platform hints are applied pre-paint (no first-frame ⌘ flash on Windows)', () => {
  // <head> 预绘制脚本必须拿注入的平台标记，先打 data-platform 再存 __TD_PLATFORM__
  assert.equal(html.includes('const platToken = "__TINGDAO_PLATFORM__"'), true, 'head reads injected platform token');
  assert.equal(/document\.documentElement\.dataset\.platform =/.test(html), true, 'head stamps data-platform pre-paint');
  assert.equal(html.includes('window.__TD_PLATFORM__ = plat'), true, 'head exposes platform to body script');
  // body 用注入值初始化 hostPlatform，并在解析阶段同步套用一次（不等 status）
  assert.equal(html.includes("let hostPlatform = window.__TD_PLATFORM__ || 'Darwin'"), true);
  assert.equal(html.includes('syncPlatformUI(hostPlatform);'), true, 'boot applies platform synchronously');
});
