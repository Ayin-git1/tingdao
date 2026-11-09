const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const fn = name => html.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`))[0];
const line = name => html.match(new RegExp(`^function ${name}\\(.*$`, 'm'))[0];

function setup(extra = {}) {
  const calls = [], toasts = [], rendered = [];
  const nodes = {findInput:{value:''}, replaceInput:{}};
  const ctx = vm.createContext({
    calls, toasts, rendered, Math, console,
    $:id => nodes[id] || null,
    document:{body:{classList:{contains:()=>false}}, querySelector:()=>null},
    hostPlatform:'Darwin', state:'idle', jobs:{}, gr:{open:false}, editing:null,
    view:{id:'a', segments:[{t:1, text:'新句', ed:1, formats:undefined}]},
    typingHere:e=>!!e.typing, toast:m=>toasts.push(m), editBarOff(){}, editBar:(h)=>calls.push(['bar',h]),
    segEls:[], segElAt:()=>({dataset:{raw:'新句'}}), renderSegmentText:(el,t)=>rendered.push(t), findOpen:()=>false,
    ICO_UNDO:'', ICO_OK:'', esc:x=>x, renderTimelineNotes(){}, revealNoteHistory(){}, revealHistoryRow(){}, refreshHistory(){},
    transcriptFormatBusy:false, hideTranscriptFormatTools(){}, findHits:[], clearFind(){},
    api:async (url, body)=>{ calls.push([url, body]); return url.endsWith('format') ? {ok:true} : {ok:true, text:body.text}; },
    ...extra,
  });
  vm.runInContext(`var editUndo=[],editRedo=[],editUndoBusy=false,findUndoArmed=false;${line('editUndoKeyLabel')}\n${line('editUndoFor')}\n${line('editRedoFor')}\n${line('undoEdit')}\n${line('redoEdit')}\n${line('noteHistoryKey')}\n${fn('pushEditHistory')}\n${fn('recordNoteHistory')}\n${fn('applyNoteHistory')}\n${fn('formatHistoryKey')}\n${fn('applyFormatHistory')}\n${fn('editHistoryStep')}\n${fn('handleEditHistoryKey')}`, ctx);
  return ctx;
}
const key = (over={}) => { const e={target:{},prevented:false,preventDefault(){this.prevented=true;},...over}; return e; };
const entry = (over={}) => ({sid:'a', t:1, old:'旧句', text:'新句', ...over});

test('⌘Z restores the last edit of the current project', async ()=>{
  const ctx = setup(); ctx.editUndo.push(entry());
  const e = key(); ctx.handleEditHistoryKey(e,-1); await new Promise(r=>setImmediate(r));
  assert.equal(e.prevented, true);
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.calls[0])), ['/api/edit_segment',{id:'a',t:1,text:'旧句',undo:true}]);
  assert.equal(ctx.view.segments[0].text, '旧句');
  assert.deepEqual(ctx.rendered, ['旧句']);
  assert.equal(ctx.editUndo.length, 0);
});
test('an edit made in another project is never written into the open one', async ()=>{
  const ctx = setup(); ctx.editUndo.push(entry({sid:'b'}));
  ctx.handleEditHistoryKey(key(),-1); await new Promise(r=>setImmediate(r));
  assert.equal(ctx.calls.length, 0);
  assert.equal(ctx.editUndo.length, 1);
  assert.deepEqual(ctx.toasts, ['没有可撤销的改动']);
});
test('typing keeps native text undo unless a replace just happened in the find bar', async ()=>{
  const ctx = setup(); ctx.editUndo.push(entry());
  const typing = key({typing:true}); ctx.handleEditHistoryKey(typing,-1);
  assert.equal(typing.prevented, false);
  const inFind = key({typing:true, target:ctx.$('replaceInput')});
  ctx.handleEditHistoryKey(inFind,-1); assert.equal(inFind.prevented, false);
  ctx.findUndoArmed = true;
  const armed = key({typing:true, target:ctx.$('replaceInput')});
  ctx.handleEditHistoryKey(armed,-1); await new Promise(r=>setImmediate(r));
  assert.equal(armed.prevented, true);
  assert.equal(ctx.view.segments[0].text, '旧句');
});
test('overlays, inline editing and key repeat do not trigger undo', ()=>{
  for (const over of [{gr:{open:true}}, {editing:{}}, {view:null}]) {
    const ctx = setup(over); ctx.editUndo.push(entry());
    ctx.handleEditHistoryKey(key(),-1);
    assert.equal(ctx.calls.length, 0);
  }
  const modal = setup({document:{body:{classList:{contains:()=>false}}, querySelector:()=>({})}});
  modal.editUndo.push(entry()); modal.handleEditHistoryKey(key(),-1); assert.equal(modal.calls.length, 0);
  const panel = setup(); panel.editUndo.push(entry());
  panel.handleEditHistoryKey(key({target:{closest:()=>({})}}),-1); assert.equal(panel.calls.length, 0);
  const repeat = setup(); repeat.editUndo.push(entry());
  const e = key({repeat:true}); repeat.handleEditHistoryKey(e,-1);
  assert.equal(e.prevented, true); assert.equal(repeat.calls.length, 0);
});
test('a sentence rewritten since the edit is left alone', async ()=>{
  const ctx = setup(); ctx.editUndo.push(entry({text:'更早的结果'}));
  await ctx.undoEdit();
  assert.equal(ctx.calls.length, 0);
  assert.equal(ctx.view.segments[0].text, '新句');
  assert.deepEqual(ctx.toasts, ['这句后来又变过，不能撤销了']);
});
test('failed undo keeps the entry; jobs and recording block it without consuming it', async ()=>{
  const failed = setup({api:async()=>({ok:false,error:'x'})}); failed.editUndo.push(entry());
  await failed.undoEdit(); assert.equal(failed.editUndo.length, 1);
  for (const over of [{state:'recording'}, {jobs:{a:{}}}]) {
    const ctx = setup(over); ctx.editUndo.push(entry());
    await ctx.undoEdit();
    assert.equal(ctx.calls.length, 0); assert.equal(ctx.editUndo.length, 1);
  }
});
test('undo restores the selection formats cleared by the edit', async ()=>{
  const formats = [{start:0,end:1,style:{bold:true}}];
  const ctx = setup(); ctx.editUndo.push(entry({formats}));
  await ctx.undoEdit();
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.calls[1])), ['/api/transcript_format',{id:'a',patches:[{t:1,text:'旧句',formats}]}]);
  assert.deepEqual(ctx.view.segments[0].formats, formats);
});
test('shortcut is bound per platform and listed on the shortcut card', ()=>{
  assert.match(html, /!e\.altKey && \(hostPlatform === 'Darwin' \? e\.metaKey && !e\.ctrlKey : e\.ctrlKey && !e\.metaKey\)/);
  assert.match(html, /k === 'z'\)\{ handleEditHistoryKey\(e, e\.shiftKey \? 1 : -1\)/);
  assert.match(html, /k === 'y' && !e\.shiftKey && hostPlatform !== 'Darwin'/);
  assert.match(html, /撤销上一处改动（文字、格式、图片）<\/span><kbd data-mac-shortcut="⌘ Z" data-windows-shortcut="Ctrl\+Z">/);
  assert.match(html, /重做<\/span><kbd data-mac-shortcut="⌘ ⇧ Z" data-windows-shortcut="Ctrl\+Shift\+Z">/);
});

test('redo reapplies an undone text edit; a new edit clears redo for that project only', async ()=>{
  const ctx = setup(); ctx.editUndo.push(entry());
  await ctx.undoEdit(); assert.equal(ctx.view.segments[0].text, '旧句'); assert.equal(ctx.editRedo.length, 1);
  await ctx.redoEdit(); assert.equal(ctx.view.segments[0].text, '新句'); assert.equal(ctx.editUndo.length, 1);
  assert.equal(ctx.calls.some(c=>c[1]&&c[1].text==='新句'&&c[1].undo), false);
  await ctx.undoEdit();
  ctx.editRedo.push(entry({sid:'b'}));
  ctx.pushEditHistory(entry({t:2}));
  assert.deepEqual([...ctx.editRedo].map(x=>x.sid), ['b']);
});
const noteOf = (width, extra={}) => ({t:5, text:'', content:[{type:'image', file:'note-images/a.png', displayWidth:width}], ...extra});
test('image move and resize undo by note snapshot and redo back', async ()=>{
  const ctx = setup({view:{id:'a', segments:[], notes:[noteOf(300)]}});
  ctx.api = async (url, body)=>{ ctx.calls.push([url, body]); return {ok:true, notes:[{t:body.t, text:body.text, content:body.content}]}; };
  ctx.recordNoteHistory('a', noteOf(200), noteOf(300));
  await ctx.undoEdit();
  assert.equal(ctx.calls[0][0], '/api/timeline_note_update');
  assert.equal(ctx.calls[0][1].content[0].displayWidth, 200);
  assert.equal(ctx.view.notes[0].content[0].displayWidth, 200);
  await ctx.redoEdit();
  assert.equal(ctx.view.notes[0].content[0].displayWidth, 300);
  assert.deepEqual(ctx.toasts, ['已撤销这张图的改动','已重做这张图的改动']);
});
test('deleting a note with its only image restores it from the kept file; redo deletes again', async ()=>{
  const ctx = setup({view:{id:'a', segments:[], notes:[]}});
  ctx.api = async (url, body)=>{ ctx.calls.push([url, body]);
    if(url==='/api/timeline_note'){ const note={t:body.t,text:body.text,content:body.content}; return {ok:true,note,notes:[note]}; }
    return {ok:true,notes:[]}; };
  ctx.recordNoteHistory('a', noteOf(200), null);
  await ctx.undoEdit();
  assert.equal(ctx.calls[0][0], '/api/timeline_note');
  assert.equal(ctx.calls[0][1].content[0].file, 'note-images/a.png');
  assert.equal(ctx.calls[0][1].assets.length, 0);
  await ctx.redoEdit();
  assert.equal(ctx.calls[1][0], '/api/timeline_note_delete');
  assert.equal(ctx.view.notes.length, 0);
});
test('a note changed since the image edit is not overwritten', async ()=>{
  const ctx = setup({view:{id:'a', segments:[], notes:[noteOf(999)]}});
  ctx.recordNoteHistory('a', noteOf(200), noteOf(300));
  await ctx.undoEdit();
  assert.equal(ctx.calls.length, 0);
  assert.deepEqual(ctx.toasts, ['这张图后来又变过，不能撤销了']);
  assert.equal(ctx.editUndo.length, 0);
});
test('recording a no-op image save adds nothing', ()=>{
  const ctx = setup();
  ctx.recordNoteHistory('a', noteOf(200), noteOf(200));
  assert.equal(ctx.editUndo.length, 0);
});

const bold = [{start:0,end:1,style:{bold:true}}];
test('format change undoes to the previous formats and redoes back', async ()=>{
  const ctx = setup({view:{id:'a', segments:[{t:1, text:'新句', formats:bold}]}});
  ctx.editUndo.push({sid:'a', kind:'format', parts:[{t:1, text:'新句', before:[], after:bold}]});
  await ctx.undoEdit();
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.calls[0])), ['/api/transcript_format',{id:'a',patches:[{t:1,text:'新句',formats:[]}]}]);
  assert.equal(JSON.stringify(ctx.view.segments[0].formats), '[]');
  assert.equal(ctx.rendered.length, 1);
  await ctx.redoEdit();
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.view.segments[0].formats)), bold);
  assert.deepEqual(ctx.toasts, ['已撤销格式改动','已重做格式改动']);
});
test('format undo refuses when the sentence formats changed since', async ()=>{
  const ctx = setup({view:{id:'a', segments:[{t:1, text:'新句', formats:[{start:0,end:2,style:{underline:true}}]}]}});
  ctx.editUndo.push({sid:'a', kind:'format', parts:[{t:1, text:'新句', before:[], after:bold}]});
  await ctx.undoEdit();
  assert.equal(ctx.calls.length, 0);
  assert.deepEqual(ctx.toasts, ['这段格式后来又变过，不能撤销了']);
});
test('format keys ignore a stray highlight group and empty styles like the backend', ()=>{
  const ctx = setup();
  assert.equal(ctx.formatHistoryKey([{start:0,end:1,style:{bold:true,highlightGroup:'x'}},{start:1,end:2,style:{}}]), ctx.formatHistoryKey(bold));
  assert.equal(ctx.formatHistoryKey(undefined), ctx.formatHistoryKey([]));
});
test('saving formats records one history entry for every selected sentence', ()=>{
  assert.match(html, /pushEditHistory\(\{sid:selected\.sid,kind:'format',parts:patches\.map/);
});
