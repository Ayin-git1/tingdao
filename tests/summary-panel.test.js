const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function blockBetween(source, start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing block: ${start}`);
  return source.slice(from, to);
}

function summaryRegenerateBinding(clock) {
  const match = html.match(/function bindSummaryRegenerate\(row,button,regenerate\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the summary regenerate interaction must exist');
  return Function('setTimeout', 'clearTimeout',
    `${match[0]}; return bindSummaryRegenerate;`)(clock.setTimeout, clock.clearTimeout);
}

function fakeElement() {
  const listeners = {};
  const classes = new Set();
  return {
    listeners,
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      contains: name => classes.has(name),
    },
    addEventListener: (name, fn) => { listeners[name] = fn; },
  };
}

test('generated summary panel uses an AI spark icon without a generated capsule', () => {
  const render = blockBetween(html, '  // 云端摘要块置顶(有才显示)', '  const outline=');
  assert.match(render, /className = 'seg sum summary-panel'/);
  assert.match(render, /class="summary-label"/);
  assert.match(render, /class="summary-spark"/);
  assert.match(render, /AI 摘要/);
  assert.doesNotMatch(render, /已生成/);
});

test('summary panel reuses the original card surface without a green side rail', () => {
  const styles = blockBetween(html, '  /* 云端摘要块:', '  /* ============ MD 渲染通用样式');
  assert.doesNotMatch(html, /--summary-card:/);
  assert.match(styles, /\.summary-panel\{background:var\(--card\); border:1px solid var\(--line\); border-left:1px solid var\(--line\);/);
  assert.doesNotMatch(styles, /border-left:[^;]*var\(--g/);
  assert.match(styles, /border-radius:var\(--radius-3\); padding:16px 20px 18px; margin:2px 0 20px;/);
  assert.match(styles, /box-shadow:0 2px 10px rgba\(20,30,24,\.035\)/);
  assert.match(styles, /\.summary-label\{[\s\S]*font-size:var\(--fs-meta\)/);
});

test('the whole summary header reveals the regenerate ball after 1.5 seconds and hides on leave', () => {
  let scheduled = null;
  let cleared = false;
  const clock = {
    setTimeout(fn, delay) { scheduled = {fn, delay}; return 7; },
    clearTimeout(id) { assert.equal(id, 7); cleared = true; },
  };
  const row = fakeElement();
  const button = fakeElement();
  const bind = summaryRegenerateBinding(clock);

  bind(row, button, () => {});
  row.listeners.mouseenter();
  assert.equal(row.classList.contains('regen-ready'), false);
  assert.equal(scheduled.delay, 1500);
  row.listeners.mouseleave();
  assert.equal(cleared, true);
  assert.equal(row.classList.contains('regen-ready'), false);

  row.listeners.mouseenter();
  scheduled.fn();
  assert.equal(row.classList.contains('regen-ready'), true);
  row.listeners.mouseleave();
  assert.equal(row.classList.contains('regen-ready'), false);
});

test('the regenerate control is a labeled round button and keyboard focus reveals it immediately', () => {
  const clock = {setTimeout: () => 1, clearTimeout: () => {}};
  const row = fakeElement();
  const button = fakeElement();
  let regenerated = false;
  const bind = summaryRegenerateBinding(clock);

  bind(row, button, () => { regenerated = true; });
  button.listeners.focus();
  assert.equal(row.classList.contains('regen-ready'), true);
  button.onclick();
  assert.equal(regenerated, true);

  const render = blockBetween(html, '  // 云端摘要块置顶(有才显示)', '  const outline=');
  assert.match(render, /class="summary-head"/);
  assert.match(render, /class="summary-regenerate"/);
  assert.match(render, /aria-label="重新生成摘要与章节"/);
  assert.match(render, /generateSummary\(d\.id,true\)/);
  assert.match(html, /\.summary-regenerate\{[^}]*width:28px;[^}]*height:28px;[^}]*border-radius:50%;/);
});
