const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');

function setup(selectedIds, response) {
  const start = html.indexOf('let exportBusy = false;');
  const end = html.indexOf("$('btnExport').onclick", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({
    selected: new Set(selectedIds), calls: [], toasts: [],
    lastHistRaw: [{id: 'a'}, {id: 'b'}, {id: 'p', pending: true}],
    toast(msg) { context.toasts.push(msg); },
    async api(path, body) { context.calls.push([path, body]); return response; },
  });
  vm.runInContext(html.slice(start, end), context);
  return context;
}

test('menu export packs the whole selection only when the item is part of it', () => {
  const ctx = setup(['a', 'b']);
  assert.deepEqual(Array.from(vm.runInContext('exportIdsForMenu("a")', ctx)), ['a', 'b']);
  assert.deepEqual(Array.from(vm.runInContext('exportIdsForMenu("c")', ctx)), ['c']);
  const single = setup(['a']);
  assert.deepEqual(Array.from(vm.runInContext('exportIdsForMenu("a")', single)), ['a']);
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
