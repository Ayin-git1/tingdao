const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function extractFunction(signature) {
  const start = html.indexOf(signature);
  assert.notEqual(start, -1, `${signature} should exist`);
  const bodyStart = html.indexOf('{', start);
  let depth = 0;
  for (let index = bodyStart; index < html.length; index++) {
    if (html[index] === '{') depth++;
    if (html[index] === '}' && --depth === 0) return html.slice(start, index + 1);
  }
  assert.fail(`${signature} should be complete`);
}

function autoScrollFunctions() {
  const direction = extractFunction('function sidebarAutoScrollDirection(');
  const step = extractFunction('function sidebarAutoScrollStep(');
  const controller = extractFunction('function createSidebarAutoScroller(');
  return Function(`${direction}\n${step}\n${controller}\nreturn {sidebarAutoScrollDirection, sidebarAutoScrollStep, createSidebarAutoScroller};`)();
}

test('drag auto-scroll selects only the overflowing edge zone', () => {
  const {sidebarAutoScrollDirection} = autoScrollFunctions();
  const rect = {top: 100, bottom: 500};

  assert.equal(sidebarAutoScrollDirection(120, rect, 900, 400), -1);
  assert.equal(sidebarAutoScrollDirection(260, rect, 900, 400), 0);
  assert.equal(sidebarAutoScrollDirection(480, rect, 900, 400), 1);
  assert.equal(sidebarAutoScrollDirection(120, rect, 400, 400), 0);
});

test('drag auto-scroll advances continuously and clamps at the list bounds', () => {
  const {sidebarAutoScrollStep} = autoScrollFunctions();
  const rect = {top: 100, bottom: 500};
  const list = {scrollTop: 0, scrollHeight: 900, clientHeight: 400};

  assert.equal(sidebarAutoScrollStep(list, 480, rect), true);
  assert.equal(list.scrollTop, 8);
  assert.equal(sidebarAutoScrollStep(list, 480, rect), true);
  assert.equal(list.scrollTop, 16);

  list.scrollTop = 500;
  assert.equal(sidebarAutoScrollStep(list, 480, rect), false);
  assert.equal(list.scrollTop, 500);

  list.scrollTop = 120;
  assert.equal(sidebarAutoScrollStep(list, 260, rect), false);
  assert.equal(list.scrollTop, 120);
});

test('drag auto-scroll re-hits after each frame and cancels when the pointer leaves the edge', () => {
  const {createSidebarAutoScroller} = autoScrollFunctions();
  const rect = {left: 0, top: 100, right: 290, bottom: 500};
  const list = {scrollTop: 0, scrollHeight: 900, clientHeight: 400};
  const frames = new Map();
  const cancelled = [];
  let hits = 0;
  let nextFrameId = 1;
  const schedule = callback => { const id = nextFrameId++; frames.set(id, callback); return id; };
  const cancel = id => { cancelled.push(id); frames.delete(id); };
  const scroller = createSidebarAutoScroller(
    list,
    () => rect,
    () => { hits++; },
    schedule,
    cancel,
  );

  scroller.update({clientX: 140, clientY: 480});
  assert.equal(frames.size, 1);
  const firstFrame = frames.get(1);
  frames.delete(1);
  firstFrame();
  assert.equal(list.scrollTop, 8);
  assert.equal(hits, 1);
  assert.equal(frames.size, 1);

  scroller.update({clientX: 140, clientY: 260});
  assert.deepEqual(cancelled, [2]);
  assert.equal(frames.size, 0);
});
