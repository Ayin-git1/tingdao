const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const rule = selector => {
  const start = html.indexOf(`  ${selector}{`);
  assert.notEqual(start, -1, `missing rule ${selector}`);
  return html.slice(start, html.indexOf('}', start));
};

test('drawer grab sits outside the clipped content so it can straddle the left edge', () => {
  assert.match(html, /<\/div>\s*<i class="dgrab" id="dgrab"[^>]*><\/i>\s*<\/div>\s*<!-- 模板弹窗/);
  assert.doesNotMatch(rule('.drawer'), /overflow:hidden/);
  assert.match(rule('.dwrap'), /overflow:hidden/);
  assert.match(rule('.dwrap'), /border-radius:inherit/);
});

test('drawer grab line is centered on the drawer edge and its hit area', () => {
  const grab = rule('.dgrab');
  const line = rule('.dgrab::before');
  const px = (source, name) => Number(source.match(new RegExp(`(?:^|[;{\\s])${name}:(-?\\d+)px`))[1]);
  assert.equal(px(grab, 'left') + px(grab, 'width') / 2, 0, 'hit area centered on the edge');
  assert.equal(px(grab, 'left') + px(line, 'left') + px(line, 'width') / 2, 0, 'line centered on the edge');
});

test('drawer grab line follows the theme color', () => {
  const line = rule('.dgrab::before');
  assert.match(line, /var\(--g-edge\)/);
  assert.doesNotMatch(line, /rgba\(20,20,20/);
});

test('drawer grab keeps its line and cursor during a drag via pointer capture', () => {
  assert.match(html, /\.dgrab:is\(:hover,\.dragging\)::before\{/);
  assert.match(html, /h\.setPointerCapture\(e\.pointerId\)/);
  assert.match(html, /h\.addEventListener\('pointercancel',\s*stop\)/);
});

test('drawer grab motion respects reduced motion', () => {
  assert.match(html, /@media\(prefers-reduced-motion:reduce\)\{\.dgrab::before\{transition:none;\}\}/);
});
