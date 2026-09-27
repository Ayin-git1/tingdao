const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const includes = pattern => assert.ok(pattern.test(html), `missing sidebar transition wiring: ${pattern}`);

test('promoting a hovered sidebar reuses the mounted sidebar and list nodes', () => {
  includes(/if\(document\.body\.classList\.contains\('sidehide'\)[\s\S]*?contains\('side-peek'\)\)\{\s*promoteSidebarPeek\(\);\s*return;/);
  includes(/function promoteSidebarPeek\(\)[\s\S]*?classList\.remove\('side-peek', 'side-peeked'\)/);
  includes(/function promoteSidebarPeek\(\)[\s\S]*?classList\.remove\('sidehide'\)/);
  assert.doesNotMatch(html.match(/function promoteSidebarPeek\(\)[\s\S]*?\n\}/)?.[0] || '', /cloneNode|innerHTML|renderHistory/);
});

test('the same controls move with the drawer from the inset peek to the pinned geometry', () => {
  includes(/\.sidebar\{[^}]*height:100%; translate:0 0/);
  includes(/body\.sidehide\.side-peek \.sidebar\{translate:10px 10px; height:calc\(100% - 20px\)/);
  includes(/body\.side-promoting \.sidebar\{[^}]*transition:translate \.52s cubic-bezier\(\.16,1,\.3,1\),\s*height \.52s cubic-bezier\(\.16,1,\.3,1\)/);
  const promotionCss = html.match(/body\.side-promoting \.sidebar\{[^}]*\}/)?.[0] || '';
  assert.match(promotionCss, /z-index:8/);
  assert.doesNotMatch(promotionCss, /margin-left|transform \.38s/);
  includes(/classList\.remove\('side-promoting'\);\s*\}, 560\)/);
  assert.doesNotMatch(html, /side-peek-snapshot|sidePanelEnter/);
});
