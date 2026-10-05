const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function functionSource(signature) {
  const start = html.indexOf(signature);
  assert.notEqual(start, -1, `${signature} should exist`);
  const bodyStart = html.indexOf('{', start);
  let depth = 0;
  for (let index = bodyStart; index < html.length; index += 1) {
    if (html[index] === '{') depth += 1;
    if (html[index] === '}' && --depth === 0) return html.slice(start, index + 1);
  }
  assert.fail(`${signature} should be complete`);
}

test('sidebar tabs share one list and expose the selected view accessibly', () => {
  assert.match(html, /<div class="sidebar-tabs"[^>]*role="tablist"/);
  assert.match(html, /class="sidebar-tabs-track"/);
  assert.match(html, /id="sidebarTabSlider"[^>]*aria-hidden="true"/);
  assert.match(html, /data-sidebar-tab-copy="projects"/);
  assert.match(html, /data-sidebar-tab-copy="favorites"/);
  for (const [id, tab, selected] of [
    ['sidebarTabProjects', 'projects', 'true'],
    ['sidebarTabFavorites', 'favorites', 'false'],
  ]) {
    const button = html.match(new RegExp(`<button[^>]*id="${id}"[\\s\\S]*?<\\/button>`))?.[0] || '';
    assert.match(button, /role="tab"/);
    assert.match(button, new RegExp(`data-sidebar-tab="${tab}"`));
    assert.match(button, /aria-controls="histlist"/);
    assert.match(button, new RegExp(`aria-selected="${selected}"`));
  }
  assert.equal((html.match(/id="histlist"/g) || []).length, 1);
});

test('sidebar tab drag metrics clamp, rubber-band, and resolve the nearest tab', () => {
  const source = functionSource('function sidebarTabDragMetrics(');
  const sidebarTabDragMetrics = Function(`${source}; return sidebarTabDragMetrics;`)();
  const rect = {left: 100, width: 200};

  assert.deepEqual(sidebarTabDragMetrics(150, rect), {
    progress: 0, overdrag: 0, target: 'projects',
  });
  assert.equal(sidebarTabDragMetrics(200, rect).target, 'favorites');
  assert.equal(sidebarTabDragMetrics(300, rect).progress, 1);
  assert.ok(sidebarTabDragMetrics(80, rect).overdrag < 0);
  assert.ok(sidebarTabDragMetrics(320, rect).overdrag > 0);
});

test('sidebar tab slider follows pointer input and has a reduced-motion fallback', () => {
  assert.match(html, /sidebarTabDragging/);
  assert.match(html, /setPointerCapture\(e\.pointerId\)/);
  assert.match(html, /addEventListener\('pointermove'/);
  assert.match(html, /addEventListener\('pointercancel'/);
  assert.match(html, /reducedMotion \? 0 : metrics\.overdrag/);
  assert.match(html, /@media\s*\(prefers-reduced-motion:reduce\)[\s\S]*?\.sidebar-tab-slider/);
});

test('slider spring settles after reversal and keeps the text mask aligned with its surface', () => {
  const styles = new Map();
  const track = {getBoundingClientRect:()=>({width:203}), style:{setProperty:(k,v)=>styles.set(k,parseFloat(v))}};
  const motion = {position:0, target:1, velocity:0, pressure:0, targetPressure:0, frame:0, time:0};
  const draw = Function('$','sidebarTabMotion','sidebarTabDragging','window','requestAnimationFrame',
    `${functionSource('function drawSidebarTabSlider(')}; return drawSidebarTabSlider;`)(
    ()=>track,motion,false,{matchMedia:()=>({matches:false})},()=>1);
  for(let i=1;i<=12;i++) draw(i*16);
  assert.ok(motion.position>0 && motion.position<1);
  motion.target=0;
  for(let i=13;i<=160;i++) draw(i*16);
  assert.ok(Math.abs(motion.position)<.001);
  assert.equal(motion.frame,0);
  assert.ok(Math.abs(styles.get('--tab-slider-width')-100)<.01);
  assert.ok(Math.abs(styles.get('--tab-slider-x'))<.01);
});

test('sidebar data keeps unarchived projects and filters favorites in the shared list', () => {
  const source = functionSource('function sidebarItemsForTab(');
  const sidebarItemsForTab = Function(`${source}; return sidebarItemsForTab;`)();
  const items = [
    {id: 'plain', favorite: false, archived: false},
    {id: 'favorite', favorite: true, archived: false},
    {id: 'archived-favorite', favorite: true, archived: true},
    {id: 'archived', favorite: false, archived: true},
  ];

  assert.deepEqual(sidebarItemsForTab(items, 'projects').map(item => item.id), [
    'plain', 'favorite',
  ]);
  assert.deepEqual(sidebarItemsForTab(items, 'favorites').map(item => item.id), [
    'favorite',
  ]);
});

test('refreshHistory renders the same history list from the selected sidebar tab', () => {
  assert.match(html, /let sidebarTab = 'projects'/);
  assert.match(html, /let items = sidebarItemsForTab\(raw, sidebarTab\)\.slice\(\)/);
  assert.match(html, /data-sidebar-tab/);
  assert.match(html, /function setSidebarTab\(next\)/);
  assert.match(html, /_histSig = '';[\s\S]*?refreshHistory\(\)/);
});

test('selecting a different sidebar tab refreshes the shared list', () => {
  const source = functionSource('function setSidebarTab(next)');
  let syncCount = 0;
  let refreshCount = 0;
  global.sidebarTab = 'projects';
  global._histSig = 'stale';
  global.syncSidebarTabs = () => { syncCount += 1; };
  global.refreshHistory = () => { refreshCount += 1; };

  const setSidebarTab = Function(`${source}; return setSidebarTab;`)();
  setSidebarTab('favorites');

  assert.equal(global.sidebarTab, 'favorites');
  assert.equal(global._histSig, '');
  assert.equal(syncCount, 1);
  assert.equal(refreshCount, 1);
});

test('removing the sidebar search box leaves the command palette available from the top bar', () => {
  assert.doesNotMatch(html, /sbSearchInput|btnCmdK|histQuery/);
  assert.match(html, /id="btnHistSearch"/);
  assert.match(html, /\$\('btnHistSearch'\)\.onclick = openPalette/);
});
