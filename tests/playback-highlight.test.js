const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');

function source(name) {
  return html.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`))?.[0] || '';
}

function setup(times = []) {
  const mutations = [], followed = [], rows = [];
  let datasetReads = 0;
  function makeRow(time) {
    const classes = new Set();
    const row = {dataset:{get t(){ datasetReads++; return String(time); }, set t(value){time=value;}},
      classList:{
        add(name){ mutations.push(['add', rows.indexOf(row)]); classes.add(name); },
        remove(name){ mutations.push(['remove', rows.indexOf(row)]); classes.delete(name); },
        toggle(name, on){ mutations.push(['toggle', rows.indexOf(row)]); on ? classes.add(name) : classes.delete(name); },
        contains(name){return classes.has(name);},
      }};
    rows.push(row);
    return row;
  }
  const context = vm.createContext({
    player:{currentTime:0, paused:false, ended:false}, rows, times,
    syncPlayerUI(){}, updateTranscriptAnchorActive(){}, savePos(){},
    followTo(hit){followed.push(hit);}, userScrolling:false, segEngaged:false,
    document:{createElement(){return makeRow(0);}},
    $(){return {appendChild(){}};}, fmt:String, esc:String, fixDot(){return '';},
    anchorLive(){}, spkIdx(){return 0;},
  });
  for(const time of times) makeRow(time);
  const start = html.indexOf('let lastCurHit = -1;');
  const playback = html.slice(start, html.indexOf('player.onplay =', start));
  vm.runInContext('let segEls = rows.slice(); let segTimes = times.slice(); let currentSegEl = null;'
    + source('curHit') + source('updatePlaybackHighlight') + source('resetPlaybackSegments')
    + source('addSeg') + playback, context);
  return {context, rows, mutations, followed, datasetReads:()=>datasetReads};
}

test('time lookup preserves tolerance, duplicate timestamps and backward seeks', () => {
  const times = [1, 5, 5, 10, 20];
  const {context} = setup(times);
  for(const time of [0, .94, .95, 1, 4.94, 4.95, 5, 10, 999, 2, 0]) {
    context.player.currentTime = time;
    let expected = -1;
    for(let i=0; i<times.length; i++){if(times[i] <= time+.05) expected=i;else break;}
    assert.equal(context.curHit(), expected, `time=${time}`);
  }
  assert.equal(setup().context.curHit(), -1);
});

test('5000-row lookup uses logarithmic time index access without reading DOM timestamps', () => {
  const {context, datasetReads} = setup(Array.from({length:5000}, (_, i)=>i));
  vm.runInContext(`let indexReads = 0;
    segTimes = new Proxy(segTimes, {get(target, key){if(/^\\d+$/.test(key))indexReads++;return target[key];}});`, context);
  context.player.currentTime = 4999;
  assert.equal(context.curHit(), 4999);
  assert.equal(datasetReads(), 0);
  assert.ok(vm.runInContext('indexReads', context) <= 13);
});

test('timeupdate touches only previous/current rows and skips unchanged highlight', () => {
  const {context, mutations, rows} = setup([0, 5, 10]);
  context.player.ontimeupdate();
  assert.deepEqual(mutations, [['add', 0]]);
  mutations.length = 0;
  context.player.currentTime = 1;
  context.player.ontimeupdate();
  assert.equal(mutations.length, 0);
  context.player.currentTime = 10;
  context.player.ontimeupdate();
  assert.deepEqual(mutations, [['remove', 0], ['add', 2]]);
  assert.equal(rows[0].classList.contains('cur'), false);
  assert.equal(rows[2].classList.contains('cur'), true);
});

test('backward seek and pre-transcript time remove the previous highlight', () => {
  const {context, rows} = setup([5, 10]);
  for(const time of [10, 5, 0]) {context.player.currentTime=time;context.player.ontimeupdate();}
  assert.ok(rows.every(row=>!row.classList.contains('cur')));
});

test('paused playback and user interaction still suppress auto-follow', () => {
  for(const flag of ['paused', 'ended', 'userScrolling', 'segEngaged']) {
    const {context, rows, followed} = setup([0, 5]);
    if(flag==='paused'||flag==='ended')context.player[flag]=true;else context[flag]=true;
    context.player.currentTime=5;context.player.ontimeupdate();
    assert.equal(rows[1].classList.contains('cur'), true);
    assert.equal(followed.length, 0);
  }
});

test('reset clears old index/highlight/follow state before rebuilding the same row number', () => {
  const {context, rows, followed} = setup([0, 5]);
  context.player.currentTime=5;context.player.ontimeupdate();
  context.resetPlaybackSegments();
  assert.equal(rows[1].classList.contains('cur'), false);
  assert.equal(context.curHit(), -1);
  assert.equal(vm.runInContext('lastCurHit', context), -1);
  context.addSeg({t:0, text:'new first'}, false);
  context.addSeg({t:5, text:'new second'}, false);
  followed.length=0;
  context.player.ontimeupdate();
  assert.equal(rows[3].classList.contains('cur'), true);
  assert.deepEqual(followed, [1]);
});

test('both live and loaded segment branches append numeric timestamps', () => {
  const {context} = setup();
  context.addSeg({t:0, text:'live words'}, true);
  context.addSeg({t:5, text:''}, true);
  context.addSeg({t:10, text:'loaded words', spk:'S01'}, false);
  assert.deepEqual(Array.from(vm.runInContext('segTimes', context)), [0, 5, 10]);
  context.player.currentTime=10;
  assert.equal(context.curHit(), 2);
});

test('all four transcript reset paths reset the playback index', () => {
  assert.equal((html.match(/resetPlaybackSegments\(\);/g) || []).length, 4);
  assert.equal((html.match(/segEls\s*=\s*\[\]/g) || []).length, 2);
});

test('playback emphasizes color without scaling, reflow or glow', () => {
  const focus = html.match(/#feed \.seg\.cur \.tx-focus\{([\s\S]*?)\n  \}/)?.[1] || '';
  assert.match(focus, /color:color-mix/);
  assert.match(focus, /-webkit-text-stroke:\.18px/);
  assert.doesNotMatch(focus, /transform:|filter:|text-fill-color/);
  assert.doesNotMatch(focus, /font-weight|letter-spacing|padding/);
  assert.match(html, /\.tx-focus\{display:block;width:calc\(100% \/ 1\.04\)/);
  assert.doesNotMatch(focus, /width:|font-size:|line-height:/);
  assert.doesNotMatch(html, /#feed \.seg\.cur \.tx\.image-aside-text\{transform:none;\}/);
  const {context, rows} = setup();
  context.addSeg({t:0, text:'live words'}, true);
  context.addSeg({t:5, text:'loaded words'}, false);
  for(const row of rows) assert.match(row.innerHTML, /class="tx"><span class="tx-focus">/);
});
