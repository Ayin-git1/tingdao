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
  // 浮窗形态挂在 .side-peeked(活到滑出结束), .side-peek 只管位移 → 收回途中不会先变回直角贴边
  includes(/body\.sidehide\.side-peeked \.sidebar\{[^}]*translate:10px 10px; height:calc\(100% - 20px\)/);
  includes(/body\.sidehide\.side-peek \.sidebar\{transform:translateX\(291px\);\}/);
  includes(/body\.side-promoting \.sidebar\{[^}]*transition:translate \.52s cubic-bezier\(\.16,1,\.3,1\),\s*height \.52s cubic-bezier\(\.16,1,\.3,1\)/);
  const promotionCss = html.match(/body\.side-promoting \.sidebar\{[^}]*\}/)?.[0] || '';
  assert.match(promotionCss, /z-index:8/);
  assert.doesNotMatch(promotionCss, /margin-left|transform \.38s/);
  includes(/classList\.remove\('side-promoting'\);\s*\}, 560\)/);
  assert.doesNotMatch(html, /side-peek-snapshot|sidePanelEnter/);
});

test('push collapse keeps the sidebar opaque and in step with the transcript edge', () => {
  // 推挤途中不淡出, 推到底才瞬间透明; 录音退场只靠 margin, 不叠 transform 跑双倍距离
  includes(/body\.sidehide:not\(\.side-peeked\) \.sidebar\{[^}]*opacity 0s \.58s/);
  includes(/\.sidebar\.recording\{margin-left:-291px;\}/);
});

test('clicking the toggle cancels a pending hover peek until the pointer leaves', () => {
  includes(/\$\('btnSide'\)\.onclick = e=>\{[\s\S]*?clearTimeout\(peekOpenTimer\);\s*peekSuppressed = /);
  includes(/if\(on && peekSuppressed\) return;/);
  includes(/addEventListener\('mouseleave', \(\)=>\{ peekSuppressed = false; peekRelease\(\); \}\)/);
});
