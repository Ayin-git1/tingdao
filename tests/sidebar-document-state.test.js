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

test('the recent copy owns active state when the same project is also grouped', () => {
  const source = functionSource('function sidebarItemIsActive(');
  const sidebarItemIsActive = Function(`${source}; return sidebarItemIsActive;`)();
  const recentIds = new Set(['project-a']);

  assert.equal(sidebarItemIsActive('project-a', 'recent', 'project-a', recentIds), true);
  assert.equal(sidebarItemIsActive('project-a', 'group', 'project-a', recentIds), false);
  assert.equal(sidebarItemIsActive('project-b', 'group', 'project-b', recentIds), true);
  assert.equal(sidebarItemIsActive('project-c', 'group', 'project-a', recentIds), false);
});

test('opening a home card loads without remounting the sidebar selection', async () => {
  const source = functionSource('function openHomeProject(id)');
  const openHomeProject = Function(`${source}; return openHomeProject;`)();
  let loaded = null;
  let animated = null;
  const messages = [];
  global.document = {body: {classList: {contains: () => false}}};
  global.state = 'idle';
  global.view = {id: 'project-a'};
  global.loadSession = (...args) => { loaded = args; return Promise.resolve(); };
  global.animateSidebarSelectionIn = id => { animated = id; return true; };
  global.toast = message => messages.push(message);

  await openHomeProject('project-a');

  assert.deepEqual(loaded, ['project-a', true]);
  assert.equal(animated, 'project-a');
  assert.deepEqual(messages, []);
});

test('home entry adds the active class on the next frame of the existing row', () => {
  const source = functionSource('function animateSidebarSelectionIn(');
  const animateSidebarSelectionIn = Function(`${source}; return animateSidebarSelectionIn;`)();
  let frame = null;
  const makeItem = (region) => {
    const classes = new Set([region + '-item']);
    return {
      dataset: {id: 'project-a'},
      classList: {
        add(name) { classes.add(name); },
        remove(name) { classes.delete(name); },
        contains(name) { return classes.has(name); },
      },
    };
  };
  const recent = makeItem('recent');
  const group = makeItem('group');
  global.document = {querySelectorAll: () => [recent, group]};
  global.view = {id: 'project-a'};
  global.requestAnimationFrame = callback => { frame = callback; };

  assert.equal(animateSidebarSelectionIn('project-a'), true);
  assert.equal(recent.classList.contains('on'), false);
  assert.equal(group.classList.contains('on'), false);
  frame();
  assert.equal(recent.classList.contains('on'), true);
  assert.equal(group.classList.contains('on'), false);
});

test('sidebar selection is released before the exit refresh runs', () => {
  const source = functionSource('function animateSidebarSelectionOut(');
  const animateSidebarSelectionOut = Function(`${source}; return animateSidebarSelectionOut;`)();
  let released = false;
  let timer = null;
  const active = {
    classList: {
      on: true,
      remove(name) {
        if (name === 'on') this.on = false;
      },
      contains(name) { return name === 'on' && this.on; },
    },
  };
  global.document = {querySelectorAll: () => [active]};
  global.setTimeout = (callback, delay) => {
    timer = {callback, delay};
    return timer;
  };

  animateSidebarSelectionOut(() => { released = true; });

  assert.equal(active.classList.contains('on'), false);
  assert.equal(released, false);
  assert.equal(timer.delay, 360);
  timer.callback();
  assert.equal(released, true);
});

test('exitView defers history refresh until the sidebar selection transition is released', () => {
  const source = functionSource('function exitView()');
  const exitView = Function(`${source}; return exitView;`)();
  const elements = new Map([
    ['btnSpk', {style: {}}],
    ['audiobar', {classList: {remove() {}}}],
    ['feed', {innerHTML: '', style: {}}],
    ['empty', {style: {}}],
    ['emptyText', {textContent: ''}],
    ['nameInput', {value: ''}],
    ['findbar', {classList: {remove() {}}}],
  ]);
  let refreshCount = 0;
  let releaseExit = null;
  global.$ = id => elements.get(id);
  global.renameArmed = true;
  global.setConfirm = () => {};
  global.view = {id: 'project-a'};
  global.spkOrder = ['speaker'];
  global.spkPop = () => {};
  global.player = {pause() {}, removeAttribute() {}};
  global.segEls = ['segment'];
  global.sessionName = 'project-a';
  global.defaultName = () => 'untitled';
  global.openDrawer = () => {};
  global.clearTranscriptAnchors = () => {};
  global.clearPlayerSource = () => {};
  global.selected = new Set(['project-a']);
  global._histSig = 'stale';
  global.animateSidebarSelectionOut = callback => { releaseExit = callback; };
  global.refreshHistory = () => { refreshCount += 1; };
  global.updateChrome = () => {};
  global.updateNoteBtn = () => {};
  global.updateRefineUI = () => {};

  exitView();

  assert.equal(refreshCount, 0);
  assert.equal(typeof releaseExit, 'function');
  releaseExit();
  assert.equal(refreshCount, 1);
});
