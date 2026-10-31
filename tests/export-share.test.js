const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');

function setup(selectedIds, response) {
  const start = html.indexOf('let exportBusy = false;');
  const end = html.indexOf("$('btnExport').onclick", start);
  assert.ok(start >= 0 && end > start);
  const classes = new Set();
  const elements = {exportStatus: {textContent: '', classList: {add: x=>classes.add(x), remove: x=>classes.delete(x), contains: x=>classes.has(x)}}, btnSelCancel: {onclick() { context.selected.clear(); }}};
  const context = vm.createContext({
    $(id) { return elements[id]; }, setInterval(fn) { context.tick = fn; return 1; }, clearInterval() {},
    setNotificationText(element, text) { element.textContent = text; },
    selected: new Set(selectedIds), calls: [], toasts: [],
    lastHistRaw: [{id: 'a'}, {id: 'b'}, {id: 'p', pending: true}],
    toast(msg) { context.toasts.push(msg); },
    async api(path, body) { context.calls.push([path, body]); return response; },
  });
  vm.runInContext(html.slice(start, end), context);
  context.elements = elements;
  return context;
}

test('menu export packs the whole selection only when the item is part of it', () => {
  const ctx = setup(['a', 'b']);
  assert.deepEqual(Array.from(vm.runInContext('exportIdsForMenu("a")', ctx)), ['a', 'b']);
  assert.deepEqual(Array.from(vm.runInContext('exportIdsForMenu("c")', ctx)), ['c']);
  const single = setup(['a']);
  assert.deepEqual(Array.from(vm.runInContext('exportIdsForMenu("a")', single)), ['a']);
});

test('successful batch export exits selection and releases the next export', async () => {
  const ctx = setup(['a', 'b'], {ok: true, count: 2});
  await vm.runInContext('exportSessions(["a", "b"])', ctx);
  assert.equal(ctx.selected.size, 0);
  assert.equal(ctx.elements.exportStatus.classList.contains('show'), false);
  await vm.runInContext('exportSessions(["a"])', ctx);
  assert.equal(ctx.calls.length, 2);
});

test('packing stays visible and repeated clicks explain the ongoing export', async () => {
  const ctx = setup(['a', 'b']);
  let finish;
  ctx.api = async () => new Promise(resolve => { finish = resolve; });
  const pending = vm.runInContext('exportSessions(["a", "b"])', ctx);
  assert.equal(ctx.elements.exportStatus.classList.contains('show'), true);
  await vm.runInContext('exportSessions(["a"])', ctx);
  assert.match(ctx.toasts.at(-1), /正在导出/);
  finish({ok: false, cancelled: true});
  await pending;
  assert.equal(ctx.elements.exportStatus.classList.contains('show'), false);
  assert.equal(ctx.selected.size, 2);
  assert.equal(vm.runInContext('exportBusy', ctx), false);
});

test('packing reports actual bytes and a failed export can be retried', async () => {
  const ctx = setup(['a']);
  let fail;
  ctx.api = async path => path === '/api/export_progress' ? {progress:{bytes: 10485760}} :
    new Promise((resolve, reject) => { fail = reject; });
  const pending = vm.runInContext('exportSessions(["a"])', ctx);
  await ctx.tick();
  assert.match(ctx.elements.exportStatus.textContent, /10.0 MB/);
  fail(new Error('network'));
  await pending;
  assert.equal(ctx.selected.size, 1);
  assert.equal(vm.runInContext('exportBusy', ctx), false);
  ctx.api = async () => ({ok:true, count:1});
  await vm.runInContext('exportSessions(["a"])', ctx);
  assert.equal(ctx.selected.size, 0);
});

test('export skips pending items and stays quiet when the save dialog is cancelled', async () => {
  const ctx = setup([], {ok: false, cancelled: true});
  await vm.runInContext('exportSessions(["a", "p"])', ctx);
  assert.equal(JSON.stringify(ctx.calls), JSON.stringify([['/api/export_sessions', {ids: ['a']}]]));
  assert.deepEqual(ctx.toasts, []);
  const done = setup([], {ok: true, count: 2});
  await vm.runInContext('exportSessions(["a", "b"])', done);
  assert.deepEqual(done.toasts, ['已导出 2 份文稿']);
});
