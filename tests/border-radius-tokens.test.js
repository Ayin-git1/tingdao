const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

test('defines the four radius tokens around the 13px drawer baseline', () => {
  const rootStart = html.indexOf(':root{');
  const rootEnd = html.indexOf('  *{', rootStart);
  assert.ok(rootStart >= 0 && rootEnd > rootStart, 'the root token block must exist');
  const root = html.slice(rootStart, rootEnd);
  assert.match(root, /--radius-1:4px/);
  assert.match(root, /--radius-2:99px/);
  assert.match(root, /--radius-3:13px/);
  assert.match(root, /--radius-4:999px/);
  assert.equal((root.match(/--radius-[1-4]:/g) || []).length, 4);
});

test('all interface corner radii use a token, square corners, or an explicit circle', () => {
  const atom = '(?:0|50%|var\\(--radius-[1-4]\\))';
  const valid = new RegExp(`^${atom}(?:\\s+${atom}){0,3}$`);
  const declarations = [...html.matchAll(/border-radius\s*:\s*([^;}]+)/g)];

  for (const match of declarations) {
    const value = match[1].trim();
    const line = html.slice(0, match.index).split('\n').length;
    assert.match(value, valid, `unexpected border-radius at index.html:${line}`);
  }

  assert.doesNotMatch(html, /\bround\s+[0-9.]+px/, 'clip-path corner radii must use the same tokens');
});

test('ordinary rectangular controls stay on the 13px radius tier', () => {
  const radius2Usages = [...html.matchAll(/var\(--radius-2\)/g)];
  assert.equal(radius2Usages.length, 0, 'the 99px tier must not leak into ordinary controls');

  const ruleBody = (selector) => {
    const start = html.indexOf(selector);
    assert.ok(start >= 0, `missing CSS selector: ${selector}`);
    const end = html.indexOf('}', start);
    assert.ok(end > start, `unterminated CSS rule: ${selector}`);
    return html.slice(start, end);
  };

  for (const selector of [
    '.info-card{',
    'body:not(.batchmode) .hitem.on,body:not(.batchmode) .hitem.on:hover{',
    '.hmenu{',
    '.setpop .seg, .cloudpop .seg{',
    '.cloudpop input{',
    '.appearance-group{',
    '.tplpop .tpl{',
    '.tplpop .add{',
    '.tplpop .go{',
    '.drawer{',
  ]) {
    assert.match(ruleBody(selector), /border-radius:var\(--radius-3\)/, `${selector} should use radius-3`);
  }

  assert.match(ruleBody('.cloudpop .thinksw{'), /border-radius:var\(--radius-4\)/, 'switch tracks remain pills');
  assert.match(ruleBody('  .sbtn{'), /border-radius:50%/, 'circular toolbar controls stay explicit circles');
});
