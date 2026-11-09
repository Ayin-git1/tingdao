const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');

function functionSource(marker, from = 0) {
  const start = html.indexOf(marker, from);
  assert.ok(start >= 0, marker);
  let depth = 0;
  for (let i = html.indexOf('{', start + marker.length - 1); i < html.length; i++) {
    if (html[i] === '{') depth++;
    if (html[i] === '}' && --depth === 0) return html.slice(start, i + 1);
  }
  throw new Error(`unterminated: ${marker}`);
}

function press(code, { job, paused = true } = {}) {
  let handler, prevented = false;
  const calls = [];
  const context = vm.createContext({
    document: { addEventListener: (_, fn) => { handler = fn; }, querySelector: () => null },
    $: () => ({ classList: { contains: () => false } }),
    hostPlatform: 'Darwin', recordStartShortcut: { key: 'r', shift: true },
    typingHere: () => false, toast() {},
    view: { id: 'a' }, jobs: job ? { a: job } : {},
    player: {
      src: 'audio.wav', paused, ended: false, getAttribute: () => 'audio.wav',
      play: () => { calls.push('play'); return Promise.resolve(); },
      pause: () => { calls.push('pause'); },
    },
    jumpLine: dir => { calls.push(`jump:${dir}`); },
  });
  vm.runInContext(functionSource('function projectLockedByJob('), context);
  vm.runInContext(`${functionSource("document.addEventListener('keydown', e=>{", html.indexOf('/* ---- 键盘快捷键 ----'))});`, context);
  const key = { Space: ' ', ArrowDown: 'ArrowDown', ArrowUp: 'ArrowUp' }[code];
  handler({ code, key, preventDefault: () => { prevented = true; } });
  return { calls, prevented };
}

for (const kind of ['refine', 'import', 'cloud']) {
  for (const state of ['run', 'wait']) {
    test(`${kind}/${state}: space and line jumps cannot start playback`, () => {
      const job = { kind, state };
      for (const code of ['Space', 'ArrowDown', 'ArrowUp']) {
        const { calls, prevented } = press(code, { job });
        assert.deepEqual(calls, [], code);
        assert.equal(prevented, true, code); // 也别让空格滚动页面或触发焦点按钮
      }
    });
  }
}

test('audio already playing when the lock begins can still be paused with space', () => {
  assert.deepEqual(press('Space', { job: { kind: 'refine', state: 'run' }, paused: false }).calls, ['pause']);
});

test('space and line jumps keep working without a locking job', () => {
  for (const job of [undefined, { kind: 'summary', state: 'run' }, { kind: 'note', state: 'run' }, { kind: 'refine', state: 'done' }]) {
    assert.deepEqual(press('Space', { job }).calls, ['play']);
    assert.deepEqual(press('Space', { job, paused: false }).calls, ['pause']);
    assert.deepEqual(press('ArrowDown', { job }).calls, ['jump:1']);
    assert.deepEqual(press('ArrowUp', { job }).calls, ['jump:-1']);
  }
});
