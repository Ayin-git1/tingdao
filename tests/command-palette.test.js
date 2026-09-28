const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function functionSource(signature) {
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

test('Command-K finds matching group names alongside matching projects', () => {
  const source = functionSource('function palMatches(q)');
  const palMatches = Function('lastHistRaw', 'groupNamesWithCounts', `${source}; return palMatches;`)([
    {id: 'project-a', name: '晨间复盘', group: '学习计划', date: '2026-09-28'},
    {id: 'project-b', name: '读书会', date: '2026-09-27'},
  ], () => [{name: '学习计划', count: 1}, {name: '工作', count: 1}]);

  assert.deepEqual(palMatches('学习').map(item => [item.type, item.id || item.name]), [
    ['project', 'project-a'],
    ['group', '学习计划'],
  ]);
  assert.deepEqual(palMatches('晨').map(item => [item.type, item.id]), [
    ['project', 'project-a'],
  ]);
});

test('Command-K project selection marks the sidebar item before loading it', async () => {
  const source = functionSource('async function palOpenProject(id)');
  const classList = () => ({
    values: new Set(),
    add(value) { this.values.add(value); },
    remove(value) { this.values.delete(value); },
    contains(value) { return this.values.has(value); },
  });
  const current = {dataset: {id: 'current'}, classList: classList()};
  current.classList.add('on');
  const destination = {dataset: {id: 'project-a'}, classList: classList(), scrollIntoView() { this.scrolled = true; }};
  global.document = {querySelectorAll: () => [current, destination]};
  global.state = 'idle';
  global.closePalette = () => { global.closed = true; };
  global.loadSession = async id => { global.loaded = id; };

  const palOpenProject = Function(`${source}; return palOpenProject;`)();
  await palOpenProject('project-a');

  assert.equal(global.closed, true);
  assert.equal(global.loaded, 'project-a');
  assert.equal(current.classList.contains('on'), false);
  assert.equal(destination.classList.contains('on'), true);
  assert.equal(destination.scrolled, true);
});

test('Command-K group selection clears the sidebar title filter and reveals the group', async () => {
  const source = functionSource('async function palOpenGroup(name)');
  const body = {classList: {contains: () => true}};
  const header = {
    dataset: {g: '学习计划'}, nextElementSibling: body,
    getBoundingClientRect: () => ({top: 360}),
  };
  global.document = {querySelectorAll: () => [header]};
  const sidebarSearch = {value: '旧搜索'};
  const historyList = {scrollTop: 320, getBoundingClientRect: () => ({top: 100})};
  global.$ = id => ({sbSearchInput: sidebarSearch, histlist: historyList})[id];
  global.histQuery = '旧搜索';
  global.closePalette = () => { global.closed = true; };
  global.refreshHistory = async () => { global.refreshed = true; };
  global.toggleGroupCollapse = (...args) => { global.expanded = args; };

  const palOpenGroup = Function(`${source}; return palOpenGroup;`)();
  await palOpenGroup('学习计划');

  assert.equal(global.closed, true);
  assert.equal(global.histQuery, '');
  assert.equal(global.$('sbSearchInput').value, '');
  assert.equal(global.refreshed, true);
  assert.deepEqual(global.expanded, ['学习计划', header, body]);
  assert.equal(historyList.scrollTop, 562);
});

test('hovering a Command-K result does not remount the clicked row', () => {
  const source = functionSource('function palRender()');
  const hoverHandler = source.match(/el\.onmouseenter = \(\)=>\{[\s\S]*?\};/)?.[0] || '';

  assert.doesNotMatch(hoverHandler, /palRender\(\)/);
  assert.match(hoverHandler, /classList\.toggle\('cur', index===i\)/);
});
