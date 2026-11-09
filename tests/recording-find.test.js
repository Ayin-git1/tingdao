const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');

function harness() {
  const elements = new Map();
  function $(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        hidden: true, value: '', innerHTML: '', scrollTop: 0, clientHeight: 100,
        classList: {
          add: name => classes.add(name), remove: name => classes.delete(name),
          contains: name => classes.has(name),
          toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
        },
        getAttribute: () => 'false', setAttribute() {}, focus() {}, select() {}, querySelectorAll: () => [],
        addEventListener() {}, style: {getPropertyValue: () => '', setProperty() {}, removeProperty() {}},
        scrollTo({top}) { this.scrollTop = top; },
      });
    }
    return elements.get(id);
  }
  function row(text, top) {
    return Object.assign($('row' + top), {
      dataset: {raw: text, t: String(top)}, offsetTop: top, innerHTML: text,
    });
  }
  const first = row('第一段说到边界', 200);
  let selected = false;
  const ctx = vm.createContext({
    $, state: 'recording', view: null, segEls: [first],
    userScrolling: false, scrollTimer: null, document: {querySelector: () => null},
    findHits: [], findPos: -1, findTimer: null, clearTimeout,
    placeFind() {}, toast() {}, matchMedia: () => ({matches: true}),
    segOf: () => undefined, fmt: String, esc: String,
    transcriptSelectionInProgress: () => selected,
    clearTranscriptTextSelection: () => { selected = false; },
  });
  $('feed').offsetTop = 0;
  $('feed').offsetHeight = 900;
  for (const [start, end] of [
    ['function anchorLive()', 'function addSeg('],
    ['function findOpen()', "$('findClose').onclick"],
    ['function findMatchCase()', 'async function replaceCurrentFind('],
  ]) {
    vm.runInContext(html.slice(html.indexOf(start), html.indexOf(end)), ctx);
  }
  $('findInput').value = '边界';
  return {ctx, $, first, selectText: () => { selected = true; }};
}

test('recording search lists settled text without rewriting or scrolling the live transcript', () => {
  const {ctx, $, first} = harness();
  $('btnFind').onclick();
  assert.equal(ctx.findOpen(), true);
  assert.match($('findRes').innerHTML, /第一段说到<mark>边界<\/mark>/);
  assert.equal(first.innerHTML, '第一段说到边界');
  assert.equal($('feedwrap').scrollTop, 0);
  assert.equal($('findReplToggle').hidden, true);
  ctx.appendRecordingFindResult({dataset: {raw: '稍后又提到边界', t: '235'}});
  assert.match($('findRes').innerHTML, /稍后又提到/);
  assert.equal(ctx.findHits.length, 2);
});

test('choosing a live result keeps the position until explicitly returning to live', () => {
  const {ctx, $, selectText} = harness();
  $('btnFind').onclick();
  ctx.landFind();
  assert.equal(ctx.findOpen(), false);
  assert.equal($('feedwrap').scrollTop, 150);
  assert.equal($('btnReturnLive').hidden, false);
  ctx.anchorLive();
  assert.equal($('feedwrap').scrollTop, 150);
  selectText();
  $('btnReturnLive').onclick();
  assert.equal($('feedwrap').scrollTop, 838);
  assert.equal($('btnReturnLive').hidden, true);
});

test('paused recording can search and stopping clears both the panel and the review position', () => {
  const {ctx, $} = harness();
  ctx.state = 'paused';
  ctx.syncRecordingFind();
  $('btnRecordingFind').onclick();
  ctx.landFind();
  $('btnRecordingFind').onclick();
  ctx.state = 'stopping';
  ctx.syncRecordingFind();
  assert.equal(ctx.findOpen(), false);
  assert.equal(ctx.findHits.length, 0);
  assert.equal($('btnRecordingFind').hidden, true);
  assert.equal($('btnReturnLive').hidden, true);
});

test('recording search explains empty and missing results by recording state', () => {
  const {ctx, $, first} = harness();
  $('btnRecordingFind').onclick();
  ctx.segEls.length = 0;
  ctx.renderFindResults();
  assert.match($('findRes').innerHTML, /还没有可查找的内容/);
  ctx.segEls.push(first);
  $('findInput').value = '没有这个词';
  ctx.runFind();
  assert.match($('findRes').innerHTML, /之后讲到时/);
  assert.equal($('findCnt').textContent, '');
  ctx.state = 'paused';
  ctx.runFind();
  assert.match($('findRes').innerHTML, /已转写的内容里没有这个词/);
});

test('the return control only says back to live', () => {
  const start = html.indexOf('<button type="button" id="btnReturnLive"');
  const button = html.slice(start, html.indexOf('</button>', start));
  assert.match(button, />\s*回到实时<svg/);
  assert.doesNotMatch(button, /rl-state|回到末尾/);
});

test('unrelated shortcuts and hidden areas are blocked during recording', () => {
  const start = html.indexOf("if(!['recording','paused','stopping'].includes(state))return;");
  const guard = html.slice(start, html.indexOf('},true);', start));
  assert.match(guard, /\['k','b','u','e',',','\/'\]/);
  assert.match(guard, /event\.code==='Space'/);
  assert.match(guard, /stopImmediatePropagation/);
  for (const part of [/\.sidebar'\)\.inert = rec/, /\$\('drawer'\)\.inert = rec/, /\$\('selbar'\)\.inert = rec/]) assert.match(html, part);
});

test('find keyboard handling respects IME composition and key repeat', () => {
  assert.match(html, /\$\('findInput'\)\.addEventListener\('keydown', e=>\{[\s\S]{0,120}e\.isComposing \|\| e\.keyCode === 229/);
  assert.match(html, /\$\('btnReturnLive'\)\.addEventListener\('keydown', e=>\{ if\(e\.repeat\) e\.preventDefault\(\); \}\)/);
});

test('hidden topbar controls stop taking clicks and keyboard focus', () => {
  assert.match(html, /\.topbar\.hide\{[^}]*visibility:hidden/);
  assert.match(html, /\.topbar\.hide > \*\{pointer-events:none!important;\}/);
});

test('recording status has no chrome and sits on the toolbar centerline, right on mac and left on Windows', () => {
  assert.match(html, /\.hang\{position:fixed; top:9px; height:38px; right:\d+px; justify-content:center;/);
  assert.match(html, /html\[data-platform="windows"\] \.hang\{top:0; height:34px; left:26px; right:auto;\}/);
  assert.match(html, /\.statepill\{[^}]*background:none; border:none; padding:0;\}/);
  assert.doesNotMatch(html, /html\[data-appearance="dark"\] \.statepill/);
});

test('search results use the same rail as the current transcript row', () => {
  assert.match(html, /\.findbar \.fr\.cur::before\{[^}]*top:5px; bottom:5px; left:0; width:3px; border-radius:2px; background:var\(--g\)/);
  assert.doesNotMatch(html, /\.fr\.cur\{[^}]*box-shadow/);
  assert.doesNotMatch(html, /findLand[^}]*inset 2px/);
});

test('command F opens recording search ahead of an outdated shell menu script', () => {
  const start = html.indexOf("window.addEventListener('keydown', e=>{\n  if(!e.metaKey");
  assert.ok(start > 0);
  const block = html.slice(start, html.indexOf('}, true);', start));
  assert.match(block, /recordingFindAvailable\(\)/);
  assert.match(block, /stopImmediatePropagation/);
  assert.match(block, /\$\('btnRecordingFind'\)\.click\(\)/);
});

test('the return control lives in the recording dock and search entry in the title row', () => {
  const dock = html.indexOf('<div class="dockgrp" id="dockgrp">');
  assert.ok(html.indexOf('id="btnReturnLive"') > dock);
  assert.ok(html.indexOf('id="btnRecordingFind"') < dock);
});
