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

test('recent sidebar items are the latest three non-pending projects', () => {
  const source = functionSource('function sidebarRecentItems(');
  const sidebarRecentItems = Function(`${source}; return sidebarRecentItems;`)();
  const items = [
    {id: 'old', date: '2026-09-01 09:00'},
    {id: 'newest', date: '2026-10-03 12:00'},
    {id: 'pending', date: '2026-10-04 12:00', pending: true},
    {id: 'middle', date: '2026-10-02 12:00'},
    {id: 'recent', date: '2026-10-01 12:00'},
  ];

  assert.deepEqual(sidebarRecentItems(items).map(item => item.id), [
    'newest', 'middle', 'recent',
  ]);
});

test('sidebar group items keep saved order, count members, and retain empty groups', () => {
  const source = functionSource('function sidebarGroupItems(');
  const sidebarGroupItems = Function(`${source}; return sidebarGroupItems;`)();
  const items = [
    {id: 'loose', group: ''},
    {id: 'b', group: '重点'},
    {id: 'a', group: '重点'},
    {id: 'unlisted', group: '临时'},
    {id: 'pending', group: '重点', pending: true},
  ];

  assert.deepEqual(sidebarGroupItems(items, {
    order: ['重点', '空组'],
    colors: {重点: 'blue', 空组: 'red'},
  }), [
    {name: '', count: 1, color: ''},
    {name: '重点', count: 2, color: 'blue'},
    {name: '空组', count: 0, color: 'red'},
    {name: '临时', count: 1, color: ''},
  ]);
});

test('sidebar section headers expose distinct accessible SVG icons', () => {
  const source = functionSource('function sidebarSectionIcon(');
  const sidebarSectionIcon = Function(`${source}; return sidebarSectionIcon;`)();
  const recentIcon = sidebarSectionIcon('recent');
  const groupsIcon = sidebarSectionIcon('groups');

  assert.match(recentIcon, /<svg[^>]+class="sbsection-icon"/);
  assert.match(recentIcon, /aria-hidden="true"/);
  assert.match(recentIcon, /<circle/);
  assert.match(groupsIcon, /<path/);
  assert.equal((groupsIcon.match(/<circle/g) || []).length, 3);
  assert.notEqual(recentIcon, groupsIcon);
});

test('recent and group sections are rendered inside the existing history list', () => {
  assert.match(html, /const recent = q \? \[\] : sidebarRecentItems\(items\)/);
  assert.match(html, /sidebarSectionIcon\('recent'\)/);
  assert.match(html, /sidebarSectionIcon\('groups'\)/);
  assert.match(html, /recent\.forEach\(it=>recentItems\.appendChild\(mkHistItem\(it, '', 'recent'\)\)\)/);
  assert.match(html, /function sectionize\(items\)[\s\S]*?sidebarGroupItems\(items, groupMeta\)/);
});
