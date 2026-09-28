const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function anchorSlices() {
  const match = html.match(/function transcriptAnchorSlices\(duration\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the transcript anchor slice helper must exist');
  return Function(`${match[0]}; return transcriptAnchorSlices;`)();
}

function activeAnchorIndex() {
  const match = html.match(/function transcriptAnchorIndex\(time,slices\)\{[\s\S]*?\n\}/);
  assert.ok(match, 'the active transcript anchor helper must exist');
  return Function(`${match[0]}; return transcriptAnchorIndex;`)();
}

test('anchors appear only after five minutes and divide the recording into five-minute slices', () => {
  // A wrong threshold, a missing last partial slice, or an incorrect slice edge must fail this test.
  const slices = anchorSlices();

  assert.deepEqual(slices(300), []);
  assert.deepEqual(slices(301), [
    {start: 0, end: 300},
    {start: 300, end: 301},
  ]);
  assert.deepEqual(slices(901), [
    {start: 0, end: 300},
    {start: 300, end: 600},
    {start: 600, end: 900},
    {start: 900, end: 901},
  ]);
});

test('the active anchor follows the slice containing the current playback time', () => {
  const slices = anchorSlices()(901);
  const active = activeAnchorIndex();

  assert.equal(active(0, slices), 0);
  assert.equal(active(299.9, slices), 0);
  assert.equal(active(300, slices), 1);
  assert.equal(active(900.9, slices), 3);
});
