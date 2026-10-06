const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function cssRule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = html.match(new RegExp(`(?:^|\\n)\\s*${escaped}\\{[^}]*\\}`));
  assert.ok(match, `${selector} CSS rule should exist`);
  return match[0];
}

function cssRuleMatching(pattern, label) {
  const match = html.match(pattern);
  assert.ok(match, `${label} CSS rule should exist`);
  return match[0];
}

test('glass material exposes three elevation shadow levels', () => {
  const light = cssRuleMatching(/:root\{[\s\S]*?--material-shadow-level-1:[\s\S]*?--material-shadow-level-3:[\s\S]*?\}/,
    'light shadow material tokens');
  const dark = cssRuleMatching(/html\[data-appearance="dark"\] \{[\s\S]*?--material-shadow-level-1:[\s\S]*?--material-shadow-level-3:[\s\S]*?\}/,
    'dark shadow material tokens');

  for (const token of ['--material-shadow-level-1', '--material-shadow-level-2', '--material-shadow-level-3']) {
    assert.match(light, new RegExp(`${token}:`));
    assert.match(dark, new RegExp(`${token}:`));
  }
});

test('glass controls use the intended shadow elevation', () => {
  assert.match(cssRule('.sidebar-tab-slider'), /box-shadow:var\(--material-shadow-level-1\)/);
  assert.match(cssRule('.transcript-outline-scroll'), /box-shadow:var\(--material-shadow-level-2\)/);
  assert.match(cssRule('.audiobar'), /box-shadow:var\(--material-shadow-level-3\)/);
  assert.match(cssRule('.recpill'), /box-shadow:var\(--material-shadow-level-3\)/);
  assert.match(cssRule('.recpill:not(.rec)'), /box-shadow:var\(--material-shadow-level-3\)/);
  assert.match(cssRule('.rcbtn'), /box-shadow:var\(--material-shadow-level-3\)/);

  const expandedPill = cssRuleMatching(/\.recpill:not\(\.rec\):is\(:hover,:focus-visible\)\{[^}]*\}/, 'expanded recording pill');
  assert.match(expandedPill, /box-shadow:var\(--material-shadow-level-3\)/);
});

test('recording hover keeps its red shadow', () => {
  const recordingHover = cssRuleMatching(/\.recpill\.rec:hover\{[^}]*\}/, 'recording hover');
  assert.match(recordingHover, /box-shadow:0 8px 24px rgba\(255,59,48,\.34\)/);
});

test('each shadow level uses neutral gray diffusion', () => {
  const darkStart = html.indexOf('html[data-appearance="dark"] {');
  assert.notEqual(darkStart, -1, 'dark material block should exist');
  const blocks = [html, html.slice(darkStart)];
  for (const source of blocks) {
    for (const level of [1, 2, 3]) {
      const match = source.match(new RegExp(`--material-shadow-level-${level}:[^;]+;`));
      assert.ok(match, `shadow level ${level} should exist`);
      assert.doesNotMatch(match[0], /var\(--g-rgb\)/,
        `shadow level ${level} should not use the saturated theme color`);
      assert.match(match[0], /0 \d+px \d+px rgba\((?:27,31,42|0,0,0),\./,
        `shadow level ${level} should have neutral gray diffusion`);
    }
  }
});
