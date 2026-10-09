const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');

function harness() {
  const classes = {hmenu: new Set(['show']), mvpop: new Set(['show'])};
  let listener, capture;
  const context = vm.createContext({
    menuCtx: {id: 'document'}, mvLeaveT: 1, clearTimeout() {},
    $: id => ({classList: {
      contains: name => classes[id].has(name),
      remove: name => classes[id].delete(name),
    }}),
    document: {addEventListener(type, fn, useCapture) { listener = fn; capture = useCapture; }},
  });
  for (const name of ['closeMv', 'closeItemMenu']) {
    const start = html.indexOf(`function ${name}(`);
    vm.runInContext(html.slice(start, html.indexOf('\n}', start) + 2), context);
  }
  const start = html.indexOf("document.addEventListener('contextmenu', e=>{");
  vm.runInContext(html.slice(start, html.indexOf('\n}, true);', start) + 10), context);
  return {classes, context, capture, rightClick: inside => listener({target: {closest: () => inside}})};
}

test('right-clicking the transcript dismisses the sidebar menu and move submenu before target handlers', () => {
  const h = harness();
  assert.equal(h.capture, true);
  h.rightClick(null);
  assert.equal(h.classes.hmenu.has('show'), false);
  assert.equal(h.classes.mvpop.has('show'), false);
  assert.equal(h.context.menuCtx, null);
});

test('right-clicking inside either sidebar menu preserves its active item', () => {
  for (const inside of ['hmenu', 'mvpop']) {
    const h = harness();
    h.rightClick(inside);
    assert.equal(h.classes.hmenu.has('show'), true);
    assert.equal(h.classes.mvpop.has('show'), true);
    assert.equal(h.context.menuCtx.id, 'document');
  }
});
