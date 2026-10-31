const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');

function setup(responses) {
  const start = html.indexOf('let noteImportBusy = false;');
  const end = html.indexOf("$('btnImport').onclick", start);
  assert.ok(start >= 0 && end > start, '笔记导入流程未接入');
  const elements = {};
  const get = id => elements[id] ||= {disabled: false, textContent: '', focus(){},
    classList: {add(){}, remove(){}} , addEventListener(){}};
  const ctx = vm.createContext({$: get, state: 'idle', calls: [], toasts: [], errors: [], opened: [],
    refreshed: 0, setAppMenuOpen(){},
    async api(path, body) {ctx.calls.push([path, body]); const r = responses.shift(); if(r instanceof Error) throw r; return r;},
    toast(msg){ctx.toasts.push(msg);}, showAlert(...args){ctx.errors.push(args);},
    async refreshHistory(){ctx.refreshed++;}, async loadSession(id){ctx.opened.push(id);},
  });
  vm.runInContext(html.slice(start, end), ctx);
  return {ctx, elements};
}

test('note import sits directly below the existing media import entry', () => {
  assert.match(html, /id="btnImport"[^]*?<\/button>\s*<button[^>]*id="btnImportNote"/);
});

test('ZIP import restores, refreshes and opens the returned note', async () => {
  const {ctx, elements} = setup([{path:'/tmp/lesson.zip'}, {ok:true,count:1,ids:[{id:'new',name:'课程（1）'}]}]);
  await vm.runInContext("importNoteBundle('zip')", ctx);
  assert.equal(JSON.stringify(ctx.calls), JSON.stringify([
    ['/api/pick_note_bundle',{kind:'zip'}], ['/api/import_note_bundle',{path:'/tmp/lesson.zip'}]]));
  assert.equal(ctx.refreshed, 1);
  assert.deepEqual(ctx.opened, ['new']);
  assert.deepEqual(ctx.toasts, ['已导入 1 份笔记']);
  assert.equal(elements.noteImportZip.disabled, false);
});

test('cancel is silent, unsupported input reports the reason, network failure resets busy', async () => {
  for (const responses of [[{path:''}], [{path:'/tmp/bad.zip'}, {error:'不支持此笔记包格式'}], [new Error('offline')]]) {
    const {ctx, elements} = setup(responses);
    await vm.runInContext("importNoteBundle('folder')", ctx);
    assert.equal(ctx.refreshed, 0);
    assert.equal(elements.noteImportFolder.disabled, false);
    assert.equal(vm.runInContext('noteImportBusy', ctx), false);
    if(ctx.calls.length === 2) assert.equal(ctx.errors[0][2], '不支持此笔记包格式');
  }
});

test('recording prevents choosing and disclaimer is displayed before selecting a package', async () => {
  const {ctx, elements} = setup([{disclaimer:'免责声明正文'}]);
  await elements.btnImportNote.onclick();
  assert.equal(elements.noteImportDisclaimer.textContent, '免责声明正文');
  vm.runInContext("state = 'recording'", ctx);
  await vm.runInContext("importNoteBundle('zip')", ctx);
  assert.equal(ctx.calls.length, 1);
  assert.equal(ctx.toasts.at(-1), '请先结束当前录音');
});

test('source badge shows only a validated sharing username and clears for local notes', () => {
  const start = html.indexOf('function syncNoteSource(');
  assert.ok(start >= 0, '匿名来源展示尚未实现');
  const code = html.slice(start, html.indexOf('\n}', start)+2);
  const badge = {}, text = {};
  const ctx = vm.createContext({$:id=>id==='noteSourceText'?text:badge});
  vm.runInContext(code, ctx);
  ctx.syncNoteSource({share_author:'Ayin'});
  assert.equal(badge.hidden, false);
  assert.equal(text.textContent, '来自 Ayin 分享');
  ctx.syncNoteSource({share_author:'/Users/private'});
  assert.equal(badge.hidden, true);
  assert.equal(text.textContent, '');
  ctx.syncNoteSource(null);
  assert.equal(badge.hidden, true);
});


test('share source is a quiet centered footer after the article', () => {
  const article = html.indexOf('<div id="feed"></div>');
  const source = html.indexOf('id="noteSourceBadge"');
  const title = html.slice(html.indexOf('id="titlebar"'), html.indexOf('id="feedwrap"'));
  assert.ok(source > article);
  assert.ok(!title.includes('id="noteSourceBadge"'));
  assert.match(html, /\.note-source\{[^}]*justify-content:center/);
});

test('legacy imported notes show missing author instead of silently hiding the source', () => {
  const start = html.indexOf('function syncNoteSource(');
  const code = html.slice(start, html.indexOf('\n}', start)+2);
  const badge = {}, text = {};
  const ctx = vm.createContext({$:id=>id==='noteSourceText'?text:badge});
  vm.runInContext(code, ctx);
  for(const meta of [{_tingdao_share:{exports:[{exporter:'anonymous-old-id'}]}}, {imported_note:true}]) {
    ctx.syncNoteSource(meta);
    assert.equal(badge.hidden, false);
    assert.equal(text.textContent, '分享者未记录（旧版笔记）');
  }
  ctx.syncNoteSource({name:'本地笔记'});
  assert.equal(badge.hidden,true);
});
