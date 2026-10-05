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

test('the app menu keeps settings and archive together beside the home control', () => {
  const railStart = html.indexOf('<nav class="app-rail"');
  const railEnd = html.indexOf('</nav>', railStart);
  const rail = html.slice(railStart, railEnd);
  const menuStart = html.indexOf('<div class="hmenu app-menu"');
  const menuEnd = html.indexOf('</div>', menuStart);
  const menu = html.slice(menuStart, menuEnd);

  assert.match(rail, /id="btnAppMenu"/);
  assert.doesNotMatch(rail, /navDocuments|navArchive|btnSet/);
  assert.doesNotMatch(html, /id="navDocuments"/);
  assert.match(menu, /id="btnImport"[^>]*role="menuitem"/);
  assert.equal((html.match(/id="btnImport"/g) || []).length, 1);
  assert.match(menu, /id="btnSet"/);
  assert.match(menu, /id="navArchive"[^>]*data-section="archive"/);
  assert.match(html.slice(html.indexOf('<div class="topbar">'), html.indexOf('</div>', html.indexOf('<div class="topbar">'))), /id="btnHome"/);
});

test('settings and archive use the same left-aligned menu row contract', () => {
  const menuStart = html.indexOf('<div class="hmenu app-menu"');
  const menuEnd = html.indexOf('</div>', menuStart);
  const menu = html.slice(menuStart, menuEnd);
  const itemClasses = [...menu.matchAll(/<button class="([^"]*)"[^>]*role="menuitem"/g)]
    .map(match => match[1].split(/\s+/).filter(Boolean));

  assert.deepEqual(itemClasses.map(classes => classes.includes('hmi')), [true, true, true]);
  assert.match(html, /\.app-menu \.gearbtn\{\s*justify-content:flex-start;\s*\}/);
});

test('setAppMenuOpen toggles the menu and its trigger accessibly', () => {
  const source = functionSource('function setAppMenuOpen(open)');
  const menuClasses = new Set();
  const triggerClasses = new Set();
  const menu = {
    classList: {
      toggle(name, on) { if (on) menuClasses.add(name); else menuClasses.delete(name); },
    },
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
  };
  const trigger = {
    classList: {
      toggle(name, on) { if (on) triggerClasses.add(name); else triggerClasses.delete(name); },
    },
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
  };
  let placed = null;
  global.$ = id => ({appMenu: menu, btnAppMenu: trigger})[id];
  global.placeUnder = (...args) => { placed = args; };

  const setAppMenuOpen = Function(`${source}; return setAppMenuOpen;`)();
  setAppMenuOpen(true);

  assert.equal(menuClasses.has('show'), true);
  assert.equal(triggerClasses.has('open'), true);
  assert.equal(trigger.attributes['aria-expanded'], 'true');
  assert.deepEqual(placed, [menu, trigger, 6]);

  setAppMenuOpen(false);

  assert.equal(menuClasses.has('show'), false);
  assert.equal(triggerClasses.has('open'), false);
  assert.equal(trigger.attributes['aria-expanded'], 'false');
});
