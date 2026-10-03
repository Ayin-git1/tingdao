const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function extractFunction(name) {
  const match = html.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`));
  assert.ok(match, `${name} must exist in index.html`);
  return Function(`${match[0]}; return ${name};`)();
}

test('findMatchRanges returns every non-overlapping literal occurrence', () => {
  const findMatchRanges = extractFunction('findMatchRanges');

  assert.deepEqual(findMatchRanges('错词错词', '错词'), [
    {start: 0, end: 2},
    {start: 2, end: 4},
  ]);
  assert.deepEqual(findMatchRanges('abcabc', 'bc'), [
    {start: 1, end: 3},
    {start: 4, end: 6},
  ]);
  assert.deepEqual(findMatchRanges('错词', ''), []);
  assert.deepEqual(findMatchRanges('正确', '错词'), []);
});

test('findNextHitIndex advances after the replaced occurrence and wraps', () => {
  const findNextHitIndex = extractFunction('findNextHitIndex');
  const hits = [
    {segmentIndex: 0, start: 1},
    {segmentIndex: 0, start: 5},
    {segmentIndex: 1, start: 0},
  ];

  assert.equal(findNextHitIndex(hits, 0, 2), 1);
  assert.equal(findNextHitIndex(hits, 0, 6), 2);
  assert.equal(findNextHitIndex(hits, 1, 1), 0);
  assert.equal(findNextHitIndex([], 0, 0), -1);
});

test('search rendering tracks each occurrence with its segment and range', () => {
  const runFindStart = html.indexOf('function runFind()');
  const runFindEnd = html.indexOf('function clearFind', runFindStart);
  assert.ok(runFindStart >= 0 && runFindEnd > runFindStart, 'runFind must exist');
  const runFind = html.slice(runFindStart, runFindEnd);

  assert.match(runFind, /findMatchRanges\(/);
  assert.match(runFind, /segmentIndex/);
  assert.match(runFind, /data-find-index/);
});

test('findbar exposes one-by-one replacement wired to the existing edit API', () => {
  assert.match(html, /id="replaceInput"/);
  assert.match(html, /id="findReplace"/);
  const replaceStart = html.indexOf('async function replaceCurrentFind');
  assert.ok(replaceStart >= 0, 'replaceCurrentFind must exist');
  const replaceEnd = html.indexOf('\n}', replaceStart);
  const replaceBody = html.slice(replaceStart, replaceEnd);
  assert.match(replaceBody, /api\('\/api\/edit_segment'/);
  assert.match(replaceBody, /findNextHitIndex/);
  assert.match(replaceBody, /runFind/);
});
