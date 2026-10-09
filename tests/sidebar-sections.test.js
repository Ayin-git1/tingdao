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

test('recent sidebar items include every ungrouped project in newest-first order', () => {
  const source = functionSource('function sidebarRecentItems(');
  const sidebarRecentItems = Function(`${source}; return sidebarRecentItems;`)();
  const items = [
    {id: 'old-loose', date: '2026-09-01 09:00'},
    {id: 'newest-grouped', date: '2026-10-05 12:00', group: '重点'},
    {id: 'new-loose', date: '2026-10-03 12:00'},
    {id: 'pending-loose', date: '2026-10-04 12:00', pending: true},
  ];

  assert.deepEqual(sidebarRecentItems(items).map(item => item.id), [
    'pending-loose', 'new-loose', 'old-loose',
  ]);
});

test('sidebar group items keep saved order, count members, and exclude ungrouped projects', () => {
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
    {name: '重点', count: 2, color: 'blue'},
    {name: '空组', count: 0, color: 'red'},
    {name: '临时', count: 1, color: ''},
  ]);
});

test('sectionize only returns named groups', () => {
  const groupSource = functionSource('function sidebarGroupItems(');
  const sidebarGroupItems = Function(`${groupSource}; return sidebarGroupItems;`)();
  const sectionSource = functionSource('function sectionize(');
  const sectionize = Function('groupMeta', 'sidebarGroupItems',
    `${sectionSource}; return sectionize;`
  )({order: ['重点'], collapsed: [], colors: {}}, sidebarGroupItems);

  assert.deepEqual(sectionize([
    {id: 'loose', group: ''},
    {id: 'grouped', group: '重点'},
  ]), [
    {name: '重点', items: [{id: 'grouped', group: '重点'}]},
  ]);
});

test('sidebar section headers expose distinct accessible SVG icons', () => {
  const source = functionSource('function sidebarSectionIcon(');
  const sidebarSectionIcon = Function(`${source}; return sidebarSectionIcon;`)();
  const recentIcon = sidebarSectionIcon('recent');
  const groupsIcon = sidebarSectionIcon('groups');

  assert.match(recentIcon, /<svg[^>]+class="ui-icon sbsection-icon"/);
  assert.match(recentIcon, /aria-hidden="true"/);
  assert.match(recentIcon, /<circle/);
  assert.match(groupsIcon, /<path/);
  assert.equal((groupsIcon.match(/<circle/g) || []).length, 3);
  assert.notEqual(recentIcon, groupsIcon);
});

test('recent and group sections are rendered inside the existing history list', () => {
  assert.match(html, /const recent = sidebarRecentItems\(items\)/);
  assert.match(html, /sidebarSectionIcon\('recent'\)/);
  assert.match(html, /sidebarSectionIcon\('groups'\)/);
  assert.match(html, /recent\.forEach\(it=>recentItems\.appendChild\(mkHistItem\(it, '', 'recent',\s*\n?\s*sidebarItemIsActive/);
  assert.match(html, /for\(const it of sec\.items\) gi\.appendChild\(mkHistItem\(it, '', 'group',\s*\n?\s*sidebarItemIsActive/);
  assert.match(html, /function sectionize\(items, includeEmpty=true\)[\s\S]*?sidebarGroupItems\(items, groupMeta\)/);
});

test('sort control sits left of group creation and the bottom bar has no glass blur', () => {
  const refreshSource = html.slice(html.indexOf('async function refreshHistory()'));
  assert.match(refreshSource, /我的分组[\s\S]*?id="btnSort"[\s\S]*?class="sbsection-add"/);
  const sidefootStart = html.indexOf('<div class="sidefoot">');
  const sidefoot = html.slice(sidefootStart, html.indexOf('</div>', sidefootStart) + 6);
  assert.doesNotMatch(sidefoot, /id="btnSort"/);

  const sidefootStyle = html.match(/\.sidefoot\{[\s\S]*?\}/)?.[0] || '';
  assert.match(sidefootStyle, /background:transparent/);
  assert.match(sidefootStyle, /backdrop-filter:none/);
  assert.match(sidefootStyle, /-webkit-backdrop-filter:none/);
  assert.match(sidefootStyle, /box-shadow:none/);
});
