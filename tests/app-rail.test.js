const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

test('top navigation keeps the menu trigger on a transparent rail', () => {
  assert.match(html, /<nav class="app-rail"[^>]*>[\s\S]*?id="btnAppMenu"/);
  assert.doesNotMatch(html, /rail-surface/);
  assert.match(html, /\.app-rail\{[^}]*flex-direction:row[^}]*background:transparent/);
  assert.doesNotMatch(html, /\.app-rail \.rail-surface\{/);
});

test('the menu trigger replaces the duplicate documents navigation item', () => {
  const railStart = html.indexOf('<nav class="app-rail"');
  const railEnd = html.indexOf('</nav>', railStart);
  const rail = html.slice(railStart, railEnd);
  assert.match(rail, /class="[^"]*rail-menu-btn[^"]*"/);
  assert.doesNotMatch(rail, /navDocuments|navArchive|btnSet/);
  assert.doesNotMatch(html, /id="navDocuments"/);
});

test('top navigation stays visible, follows the requested order, and shifts right on home', () => {
  const order = ['btnAppMenu', 'btnHome', 'btnNoteTop']
    .map(id => html.indexOf(`id="${id}"`));
  assert.ok(order.every((index, i) => index >= 0 && (i === 0 || index > order[i - 1])));
  assert.doesNotMatch(html, /body\.home[^}]*#appRail[^}]*display:none/);
  assert.doesNotMatch(html, /\.topbar \.app-rail\{position:absolute/);
  assert.match(html, /function syncRailVisibility\(/);
  assert.match(html, /home\.inert = homeHidden/);
  assert.match(html, /note\.inert = !noteVisible/);
  assert.match(html, /syncRailVisibility\(\);/);
});

test('settings and archive live in the app menu instead of the rail', () => {
  const menuStart = html.indexOf('<div class="hmenu app-menu"');
  const menuEnd = html.indexOf('</div>', menuStart);
  const menu = html.slice(menuStart, menuEnd);
  assert.match(menu, /id="btnSet"/);
  assert.match(menu, /id="navArchive"[^>]*data-section="archive"/);
  assert.doesNotMatch(html.slice(0, menuStart), /id="btnSet"/);
});

test('rail reserves space and collapses unavailable controls without layout reads', () => {
  assert.match(html, /\.app-rail\{[^}]*margin-left:auto/);
  assert.match(html, /body\.home \.app-rail\{width:30px/);
  assert.match(html, /\.app-rail:not\(\.note-visible\)\{width:70px/);
  assert.match(html, /home\.setAttribute\('aria-hidden', String\(homeHidden\)\)/);
  assert.match(html, /note\.setAttribute\('aria-hidden', String\(!noteVisible\)\)/);
});

test('mac topbar controls share the traffic-light centerline', () => {
  assert.match(html, /html\[data-platform="mac"\] \.topbar\{[^}]*transform:translateY\(-5px\)/);
});

test('the menu trigger exposes its expanded state and the app menu dismisses globally', () => {
  assert.match(html, /id="btnAppMenu"[^>]*aria-haspopup="menu"[^>]*aria-expanded="false"/);
  assert.match(html, /id="appMenu"[^>]*role="menu"/);
  assert.match(html, /function setAppMenuOpen\(open\)/);
  assert.match(html, /'#appMenu','#btnAppMenu'/);
  assert.match(html, /if\(\$\('appMenu'\)\.classList\.contains\('show'\)\)/);
});
