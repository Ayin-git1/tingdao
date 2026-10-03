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

test('rail and collection panel have independent navigation targets', () => {
  assert.match(html, /class="app-rail"/);
  assert.match(html, /id="navDocuments"/);
  assert.match(html, /id="navFavorites"/);
  assert.match(html, /id="navArchive"/);
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

