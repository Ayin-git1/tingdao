const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');
const source = html.slice(html.indexOf('const DOCK_PUSH ='), html.indexOf('/* ---- 录音中切换来源'));

test('Windows hides unsupported dock controls before animation and only Darwin polls volume', () => {
  assert.match(html, /html\[data-platform="windows"\] #btnCamTool,\s*html\[data-platform="windows"\] #btnVol\s*\{\s*display:none/);
  assert.match(html, /if\(dockEntering && hostPlatform === 'Darwin'\) volRefresh\(\)/);
  assert.match(html, /if\(hostPlatform === 'Darwin' && \(state==='recording'\|\|state==='paused'\)\) volRefresh\(\)/);
});

for (const [platform, n, duration] of [['Windows', 3, 660], ['Darwin', 5, 820]]) {
  test(`${platform} uses platform timing and settled springs`, () => {
    const animations = [];
    const buttons = Array.from({length:n}, (_,i) => ({
      getAnimations: () => [], getBoundingClientRect: () => ({left:54*i}),
      animate: (frames, options) => animations.push({frames, options}),
    }));
    const context = {
      hostPlatform: platform, matchMedia: () => ({matches:false}),
      getComputedStyle: () => ({display:'flex'}),
      $: id => id === 'fab' ? {getBoundingClientRect: () => ({left:n*54})} : {querySelectorAll: () => buttons},
    };
    vm.createContext(context);
    vm.runInContext(source + ';pushDockButtons();globalThis.last = dockBrakeSim(' + n + ').at(-1);', context);
    assert.equal(animations.length, n);
    assert.ok(animations.every(a => a.options.duration === duration));
    if (platform === 'Windows') assert.ok(context.last.every(y => Math.abs(y) < .5));
    const firstBrake = animations[0].frames.find(f => f.opacity === 1 && f.transform.startsWith('translateX(0.00px)'));
    assert.ok(firstBrake);
    assert.equal(Math.round(firstBrake.offset * duration), platform === 'Windows' ? 180 : 300);
  });
}
