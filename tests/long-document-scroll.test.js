const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('index.html', 'utf8');
function helper(name) {
  const source = html.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));
  assert.ok(source, `${name} exists`);
  return Function(`${source[0]}; return ${name}`)();
}
test('4042 paragraph lookup is logarithmic and reuses document coordinates across scrolls', () => {
  const locate = helper('transcriptScrollSegmentIndex');
  const positions = new Map();
  let reads = 0, scrollTop = 0;
  const rows = Array.from({length:4042}, (_, i) => ({getBoundingClientRect() {
    reads++; return {top:100+i*50-scrollTop};
  }}));
  assert.equal(locate(rows, 100+3000*50+20, 100, 0, positions), 3000);
  assert.ok(reads <= 13, `read ${reads} rows`);
  const firstReads = reads;
  scrollTop = 500;
  assert.equal(locate(rows, 100+3000*50+20-500, 100, 500, positions), 3000);
  assert.equal(reads, firstReads);
  positions.clear();
  assert.equal(locate(rows, 99, 100, 500, positions), 9);
  assert.equal(locate([], 100, 100, 0, positions), -1);
});
test('invalidated positions follow edited paragraph heights and document replacement', () => {
  const locate = helper('transcriptScrollSegmentIndex');
  const positions = new Map();
  let tops = [0, 50, 100, 150];
  const rows = tops.map((_, i) => ({getBoundingClientRect: () => ({top:tops[i]})}));
  assert.equal(locate(rows, 110, 0, 0, positions), 2);
  tops = [0, 150, 200, 250]; positions.clear();
  assert.equal(locate(rows, 110, 0, 0, positions), 0);
  positions.clear();
  assert.equal(locate([{getBoundingClientRect:()=>({top:0})}], 110, 0, 0, positions), 0);
});
test('layout invalidation ignores playback highlight but catches content and style changes', () => {
  const changed = helper('transcriptLayoutChanged');
  const cls = (before, after) => ({type:'attributes',attributeName:'class',oldValue:before,
    target:{getAttribute:()=>after}});
  assert.equal(changed([cls('seg', 'seg cur')]), false);
  assert.equal(changed([cls('seg cur hl', 'seg find-land')]), false);
  assert.equal(changed([cls('seg', 'seg image-aside-row')]), true);
  assert.equal(changed([{type:'characterData'}]), true);
  assert.equal(changed([{type:'childList'}]), true);
  assert.equal(changed([{type:'attributes',attributeName:'style'}]), true);
});
test('persistent order keeps headings, segments and notes aligned and rejects broken indices', () => {
  const content = helper('transcriptContentItems');
  const segments = [{t:20,text:'later'}, {t:0,text:'first'}];
  const notes = [{t:10,text:'note'}], outline = [{t:0,level:1,title:'chapter'}];
  const expected = [['heading',0],['seg',0],['note',10],['seg',20]];
  for(const order of [[0,2,3,1], [0,0,3,1], [0,2,3,99], null])
    assert.deepEqual(content(segments,notes,outline,order).map(item=>[item.type,item.t]), expected);
});
