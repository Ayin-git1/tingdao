const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

test('top navigation keeps only the theme indicator on a transparent rail', () => {
  assert.match(html, /<nav class="app-rail"[^>]*>[\s\S]*?<span class="rail-indicator"[^>]*><\/span>/);
  assert.doesNotMatch(html, /rail-surface/);
  assert.match(html, /\.app-rail\{[^}]*flex-direction:row[^}]*background:transparent/);
  assert.match(html, /\.app-rail \.rail-indicator\{[^}]*background:var\(--g\)/);
  assert.doesNotMatch(html, /\.app-rail \.rail-surface\{/);
});

test('each primary navigation item expands with its icon and label', () => {
  for (const [id, label] of [['navDocuments', '文稿'], ['navFavorites', '收藏'], ['navArchive', '归档']]) {
    const button = html.match(new RegExp(`<button class="rail-btn[^>]*" id="${id}"[\\s\\S]*?<\\/button>`))?.[0] || '';
    assert.match(button, new RegExp(`<span class="rail-label">${label}<\\/span>`));
  }
  assert.match(html, /\.app-rail \.rail-btn\.active\{[^}]*width:calc\(/);
  assert.match(html, /\.app-rail \.rail-label\{[^}]*max-width:0/);
  assert.match(html, /\.app-rail \.rail-btn\.active \.rail-label\{[^}]*max-width:/);
  assert.match(html, /label\.style\.maxWidth\s*=\s*'none'/);
  assert.match(html, /const labelWidth\s*=\s*label\.scrollWidth/);
});

test('rail indicator follows the hovered or selected button without changing navigation state', () => {
  assert.match(html, /function syncRailIndicator\(/);
  assert.match(html, /railIndicatorTarget/);
  assert.match(html, /btn\.addEventListener\('mouseenter'/);
  assert.match(html, /btn\.addEventListener\('focusin'/);
  assert.match(html, /btn\.addEventListener\('mouseleave'/);
});

test('top navigation stays visible, follows the requested order, and shifts right on home', () => {
  const order = ['navFavorites', 'navArchive', 'navDocuments', 'btnHome', 'btnNoteTop']
    .map(id => html.indexOf(`id="${id}"`));
  assert.ok(order.every((index, i) => index >= 0 && (i === 0 || index > order[i - 1])));
  assert.doesNotMatch(html, /body\.home[^}]*#appRail[^}]*display:none/);
  assert.doesNotMatch(html, /\.topbar \.app-rail\{position:absolute/);
  assert.match(html, /\.app-rail \.rail-indicator\{[^}]*top:30px/);
  assert.match(html, /\.app-rail \.rail-btn\{[^}]*transform:translateX\(var\(--rail-shift/);
  assert.match(html, /\.app-rail \.rail-btn:nth-of-type\(1\)\{--rail-delay:0ms/);
  assert.match(html, /function syncRailPlacement\(/);
  assert.match(html, /const homeButton = \$\('btnHome'\)/);
  assert.match(html, /const drawerButton = \$\('btnNoteTop'\)/);
  assert.match(html, /getComputedStyle\(homeButton\)\.display === 'none'/);
  assert.match(html, /getComputedStyle\(drawerButton\)\.display === 'none'/);
  assert.match(html, /syncRailPlacement\(\);/);
});

test('rail stays beside the visible home control instead of resetting to the left', () => {
  assert.match(html, /const gap = parseFloat\(getComputedStyle\(topbar\)\.gap\)/);
  assert.match(html, /const homeRect = homeButton && homeButton\.getBoundingClientRect\(\)/);
  assert.match(html, /const railRect = rail\.getBoundingClientRect\(\)/);
  assert.doesNotMatch(html, /if\(!homeControlsHidden\)\{\s*rail\.style\.setProperty\('\\-\\-rail\\-shift', '0px'\);\s*return;/);
});

test('mac topbar controls share the traffic-light centerline', () => {
  assert.match(html, /html\[data-platform="mac"\] \.topbar\{[^}]*transform:translateY\(-5px\)/);
});

test('rail buttons use a short stagger when shifting', () => {
  assert.match(html, /\.app-rail \.rail-btn:nth-of-type\(1\)\{--rail-delay:0ms;\}/);
  assert.match(html, /\.app-rail \.rail-btn:nth-of-type\(2\)\{--rail-delay:16ms;\}/);
  assert.match(html, /\.app-rail \.rail-btn:nth-of-type\(3\)\{--rail-delay:32ms;\}/);
  assert.match(html, /body:not\(.home\) \.app-rail \.rail-btn:nth-of-type\(1\)\{--rail-delay:32ms;\}/);
  assert.match(html, /body:not\(.home\) \.app-rail \.rail-btn:nth-of-type\(2\)\{--rail-delay:16ms;\}/);
  assert.match(html, /body:not\(.home\) \.app-rail \.rail-btn:nth-of-type\(3\)\{--rail-delay:0ms;\}/);
});
