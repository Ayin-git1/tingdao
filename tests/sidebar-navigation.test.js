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

test('sectionItems keeps archived projects out of documents and favorites', () => {
  const source = functionSource('function sectionItems(items, section)');
  const sectionItems = Function(`${source}; return sectionItems;`)();
  const items = [
    {id: 'plain', favorite: false, archived: false},
    {id: 'favorite', favorite: true, archived: false},
    {id: 'archived', favorite: true, archived: true},
    {id: 'legacy'},
  ];

  assert.deepEqual(sectionItems(items, 'documents').map(item => item.id), [
    'plain', 'favorite', 'legacy',
  ]);
  assert.deepEqual(sectionItems(items, 'favorites').map(item => item.id), ['favorite']);
  assert.deepEqual(sectionItems(items, 'archive').map(item => item.id), ['archived']);
});

test('the app menu keeps archive navigation while favorites stay in sidebar tabs', () => {
  assert.match(html, /class="app-rail"/);
  assert.doesNotMatch(html, /id="navDocuments"/);
  assert.match(html, /id="appMenu"[\s\S]*?id="navArchive"/);
  assert.doesNotMatch(html, /id="navFavorites"/);
  assert.match(html, /id="sidebarTabFavorites"/);
  assert.match(html, /id="collectionPanel"/);
});

test('goToDocumentsHome resets section and exits an open project', () => {
  const source = functionSource('function goToDocumentsHome()');
  global.section = 'archive';
  global.view = {id: 'open-project'};
  global.exitView = () => { global.exited = true; };
  const goToDocumentsHome = Function(`${source}; return goToDocumentsHome;`)();

  goToDocumentsHome();

  assert.equal(global.section, 'documents');
  assert.equal(global.exited, true);
});

test('ordinary project menu archives instead of exposing real deletion', () => {
  const menuStart = html.indexOf('<div class="hmenu" id="hmenu"');
  const menu = html.slice(menuStart, html.indexOf('</div>', menuStart) + 6);
  assert.match(menu, /data-act="favorite"/);
  assert.match(menu, /data-act="archive"/);
  assert.doesNotMatch(menu, /data-act="del"/);
});

test('archive cards expose restore and real-delete actions', () => {
  const source = functionSource('function renderCollectionPanel()');
  assert.match(source, /data-act=\\?"restore\\?"/);
  assert.match(source, /data-act=\\?"delete\\?"/);
  assert.match(source, /openDelModal\(\[id\], \{archiveDelete:true\}\)/);
});

test('setSessionFlags posts state changes and refreshes the collection', async () => {
  const source = functionSource('async function setSessionFlags(ids, flags)');
  const calls = [];
  global.api = async (path, body) => { calls.push([path, body]); return {ok: true, updated: body.ids.length}; };
  global.$ = () => ({_sig: ''});
  global.refreshHistory = async () => { global.refreshed = true; };
  const setSessionFlags = Function(`${source}; return setSessionFlags;`)();

  await setSessionFlags(['project-a'], {favorite: true});

  assert.deepEqual(calls, [['/api/session_flags', {ids: ['project-a'], favorite: true}]]);
  assert.equal(global.refreshed, true);
});

test('the drawer toolbar is transparent and the rail lives in the top chrome', () => {
  const topbar = html.slice(html.indexOf('<div class="topbar">'), html.indexOf('</div>', html.indexOf('<div class="topbar">')) + 6);
  assert.match(topbar, /id="btnAppMenu"[\s\S]*?id="btnHome"[\s\S]*?id="btnNoteTop"/);
  assert.doesNotMatch(topbar, /id="navArchive"|id="navDocuments"|id="btnSet"/);
  assert.doesNotMatch(html, /class="sbsearch"/);
  assert.match(html, /--rail-width:0px/);
  assert.doesNotMatch(html, /\.app-rail\{[^}]*border-right:/);
  const sidefoot = html.match(/\.sidefoot\{[^}]+\}/)?.[0] || '';
  assert.match(sidefoot, /left:10px/);
  assert.match(sidefoot, /right:10px/);
  assert.match(sidefoot, /background:transparent/);
  assert.match(sidefoot, /backdrop-filter:none/);
  assert.match(sidefoot, /-webkit-backdrop-filter:none/);
  assert.match(sidefoot, /box-shadow:none/);
  assert.match(html, /\.sidehide \.sidebar\{margin-left:-291px;\}/);
  assert.match(html, /id="btnSort"/);
  assert.match(html, /id="btnImport"/);
  assert.match(html, /id="sfMode"/);
  assert.match(html, /id="btnSet"/);
});
