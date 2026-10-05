const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');
function setup() {
  const listeners = {};
  const classes = new Set();
  const player = { playbackRate: 1.5, paused: false, ended: false, getAttribute: () => 'audio.wav', addEventListener: (type, fn) => { listeners[type] = fn; } };
  const context = vm.createContext({ player, document: { hidden: false, addEventListener: (type, fn) => { listeners[type] = fn; } }, window: { addEventListener: (type, fn) => { listeners[type] = fn; } }, $: () => ({ classList: { add: name => classes.add(name), remove: name => classes.delete(name) } }), syncRateUI() {}, hideResume() {} });
  const start = html.indexOf('/* ---- 按住右方向键临时加速 ---- */');
  assert.ok(start >= 0, 'temporary boost lifecycle exists');
  vm.runInContext(html.slice(start, html.indexOf('/* ---- 进度条 /', start)), context);
  return { context, player, listeners, classes };
}
test('hold uses exactly 2x, repeated keydown preserves original rate, release restores it', () => {
  const { context, player, listeners, classes } = setup();
  vm.runInContext('startPlaybackBoost(); startPlaybackBoost();', context);
  assert.equal(player.playbackRate, 2);
  assert.ok(classes.has('boosting'));
  listeners.keyup({ key: 'ArrowLeft' });
  assert.equal(player.playbackRate, 2);
  listeners.keyup({ key: 'ArrowRight' });
  assert.equal(player.playbackRate, 1.5);
  assert.equal(classes.size, 0);
});
test('pause, ended, source changes and focus loss restore rate', () => {
  for (const event of ['pause', 'ended', 'emptied', 'blur', 'pagehide', 'visibilitychange']) {
    const { context, player, listeners } = setup();
    vm.runInContext('startPlaybackBoost()', context);
    context.document.hidden = true;
    listeners[event]();
    assert.equal(player.playbackRate, 1.5, event);
  }
});
test('paused playback is not started by boost', () => {
  const { context, player, classes } = setup();
  player.paused = true;
  vm.runInContext('startPlaybackBoost()', context);
  assert.equal(player.playbackRate, 1.5);
  assert.equal(classes.size, 0);
});
test('right-arrow shortcut respects editing, modifiers, dialogs and paused playback', () => {
  const marker = "document.addEventListener('keydown', e=>{";
  const start = html.indexOf(marker, html.indexOf('/* ---- 键盘快捷键 ----'));
  let depth = 0, end;
  for (let i = start + marker.length - 1; i < html.length; i++) {
    if (html[i] === '{') depth++;
    if (html[i] === '}' && --depth === 0) { end = i + 2; break; }
  }
  for (const scenario of ['playing', 'typing', 'modifier', 'dialog', 'paused', 'no-view', 'key-card']) {
    let handler, boosted = false, prevented = false;
    const context = vm.createContext({
      document: { addEventListener: (_, fn) => { handler = fn; }, querySelector: () => scenario === 'dialog' },
      $: () => ({ classList: { contains: () => scenario === 'key-card' } }),
      hostPlatform: 'Darwin', recordStartShortcut: { key: 'r', shift: true },
      typingHere: () => scenario === 'typing', view: scenario === 'no-view' ? null : {},
      player: { paused: scenario === 'paused', ended: false, getAttribute: () => 'audio.wav' },
      startPlaybackBoost: () => { boosted = true; },
    });
    vm.runInContext(html.slice(start, end), context);
    handler({ key: 'ArrowRight', altKey: scenario === 'modifier', preventDefault: () => { prevented = true; } });
    assert.equal(boosted, scenario === 'playing', scenario);
    assert.equal(prevented, scenario === 'playing', scenario);
  }
});
