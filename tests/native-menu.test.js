const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
function setup(extra = {}) {
  const calls = [], elements = new Map(), listeners = {};
  const el = id => {
    if (!elements.has(id)) elements.set(id, {id, hidden:false, disabled:false, inert:false, style:{}, dataset:{available:'true'},
      classList:{contains:()=>false}, click:()=>calls.push(id), focus:()=>calls.push('focus:'+id), select(){},
      getAttribute:()=>null, querySelector:()=>null});
    return elements.get(id);
  };
  const context = vm.createContext({window:{}, location:{hostname:'127.0.0.1',port:'1234'},
    document:{readyState:'loading', addEventListener(type,fn){listeners[type]=fn;}, getElementById:el,
      body:{classList:{contains:()=>false}}, querySelector:()=>null},
    setInterval(){}, setTimeout(){}, console,
    state:'idle', view:null, selected:new Set(), lastHistRaw:[], jobs:{}, exportBusy:false,
    recordLoadingBusy:false, sourcePending:'', recordingImageStopping:false, cloudOK:true,
    mode:'system',recMode:'system', player:{paused:true,getAttribute:()=>''}, rateIdx:1,
    RATES:['0.75x','1x','1.25x','1.5x','2x'],recordStartShortcut:{key:'r',shift:true},
    drawerOpen:()=>false, noteJob:()=>null, typingHere:()=>false,
    exportSessions:ids=>calls.push(['export',ids]), jumpLine:dir=>calls.push(['jump',dir]),
    navigateToSection:section=>calls.push(['section',section]),
    ...extra});
  vm.runInContext(fs.readFileSync('tauri-shell/src/native_menu.js','utf8'),context);
  return {menu:context.window.tingdaoNativeMenu, calls, context, el, listeners};
}
test('home disables project commands; recording permits only recording actions',()=>{
  const {menu,context}=setup();
  let s=menu.snapshot();
  assert.equal(s.archive.enabled,false); assert.equal(s['import-media'].enabled,true);
  assert.equal(s['record-start'].enabled,true); assert.equal(s['record-stop'].enabled,false);
  context.state='recording'; s=menu.snapshot();
  for(const id of ['home','show-archive','import-media','record-start','search','sidebar']) assert.equal(s[id].enabled,false,id);
  assert.equal(s['record-stop'].enabled,true); assert.equal(s['record-pause'].enabled,true);
  context.state='paused'; assert.equal(menu.snapshot()['record-pause'].text,'继续录音');
});
test('native Find opens the recording search while replacement remains disabled',()=>{
  const {menu,calls,context}=setup({state:'recording',findOpen:()=>false});
  assert.equal(menu.snapshot().find.enabled,true);
  assert.equal(menu.snapshot().replace.enabled,false);
  menu.dispatch('find');
  assert.deepEqual(calls,['btnRecordingFind']);
  context.state='stopping';
  assert.equal(menu.snapshot().find.enabled,false);
});
test('project commands follow audio, background jobs, selection and favorite state',()=>{
  const {menu,context}=setup({view:{id:'p',hasNote:true,noteText:'notes'}, lastHistRaw:[{id:'p',favorite:true}],
    player:{paused:false,getAttribute:()=>'/audio'}});
  let s=menu.snapshot();
  assert.equal(s.favorite.text,'取消收藏'); assert.equal(s.play.enabled,true);
  assert.equal(s.play.text,'暂停'); assert.equal(s['note-copy'].enabled,true);
  context.jobs.p={kind:'note'};
  assert.equal(menu.snapshot()['note-generate'].enabled,false);
  context.exportBusy=true; assert.equal(menu.snapshot()['export-bundle'].enabled,false);
});
test('batch export targets the selected projects; disabled commands never run',()=>{
  const {menu,calls}=setup({selected:new Set(['a','b'])});
  menu.dispatch('export-bundle'); menu.dispatch('archive');
  assert.equal(calls.length,1); assert.equal(calls[0][0],'export');
  assert.deepEqual(Array.from(calls[0][1]),['a','b']);
});
test('native actions reuse existing entry points and direction semantics',()=>{
  const {menu,calls}=setup({view:{id:'p'},player:{paused:true,getAttribute:()=>'/audio'}});
  menu.dispatch('settings'); menu.dispatch('import-note'); menu.dispatch('next'); menu.dispatch('show-archive');
  assert.deepEqual(calls,['btnSet','btnImportNote',['jump',1],['section','archive']]);
});
test('modal dialog prevents unrelated project and recording commands',()=>{
  const {menu,context}=setup({view:{id:'p'}});
  context.document.querySelector=()=>({});
  const s=menu.snapshot();
  for(const id of ['archive','record-start','import-media','note-add']) assert.equal(s[id].enabled,false,id);
});
test('injection can load before any frontend globals exist',()=>{
  const context=vm.createContext({window:{},location:{hostname:'127.0.0.1',port:'1'},
    document:{readyState:'loading',addEventListener(){}},setInterval(){},setTimeout(){}});
  assert.doesNotThrow(()=>vm.runInContext(fs.readFileSync('tauri-shell/src/native_menu.js','utf8'),context));
  assert.equal(typeof context.window.tingdaoNativeMenu.dispatch,'function');
});
test('adding a note anchors to a transcript row instead of arbitrary playback seconds',()=>{
  const row={dataset:{t:'12'},classList:{contains:()=>false}};
  const {menu,el,calls,context}=setup({view:{id:'p',segments:[{t:12,text:'hello'}]},
    player:{paused:true,currentTime:14.7,getAttribute:()=>'/audio'},
    openTranscriptNote:time=>calls.push(['note',time]),transcriptNoteTargetRow:null});
  el('feed').querySelectorAll=()=>[row];
  menu.dispatch('note-add');
  assert.deepEqual(calls,[['note',12]]);
  assert.equal(context.transcriptNoteTargetRow,row);
});
test('rate selection reuses persistence handler, including selecting the current rate',()=>{
  const {menu,context,calls}=setup({view:{id:'p'},player:{paused:true,getAttribute:()=>'/audio'}});
  context.document.querySelector=selector=>selector.startsWith('#ratefan') ? {click:()=>calls.push(selector)} : null;
  menu.dispatch('rate-1');
  assert.deepEqual(calls,['#ratefan [data-v="1x"]']);
});
test('native recording dispatch cannot bypass the existing typing guard',()=>{
  const {menu,calls}=setup({typingHere:()=>true});
  menu.dispatch('record-start');
  assert.deepEqual(calls,[]);
});
test('open timeline editor protects its unsaved draft against reopening and navigation',()=>{
  const {menu,context}=setup({view:{id:'p',segments:[{t:0,text:'draft'}]}});
  context.document.querySelector=selector=>selector.includes('#transcriptNoteLayer')?{}:null;
  for(const id of ['note-add','archive','home','import-media']) assert.equal(menu.snapshot()[id].enabled,false,id);
});
test('refining locks project tools while summary generation leaves playback available',()=>{
  const {menu,context}=setup({view:{id:'p'},player:{paused:true,getAttribute:()=>'/audio'},jobs:{p:{kind:'refine',state:'run'}}});
  for(const id of ['archive','rename','play','export-bundle','find']) assert.equal(menu.snapshot()[id].enabled,false,id);
  assert.equal(menu.snapshot().home.enabled,true);
  context.jobs.p={kind:'summary',state:'run'};
  assert.equal(menu.snapshot().play.enabled,true);
});

test('disabled native shortcuts cannot fall through into old page handlers',()=>{
  const {listeners,context,calls}=setup({view:{id:'p',segments:[{text:'draft'}]}});
  context.document.querySelector=selector=>selector.includes('#transcriptNoteLayer')?{}:null;
  let prevented=false,stopped=false;
  listeners.keydown({metaKey:true,key:'n',shiftKey:false,preventDefault(){prevented=true;},stopImmediatePropagation(){stopped=true;}});
  assert.equal(prevented,true);assert.equal(stopped,true);assert.deepEqual(calls,[]);
});

test('recording leaves only recording commands enabled in the native menu',()=>{
  const {menu}=setup({state:'recording',findOpen:()=>false});
  const enabled=Object.entries(menu.snapshot()).filter(([,item])=>item.enabled).map(([id])=>id);
  for(const id of enabled) assert.match(id,/^(find|record-pause|record-stop|microphone_modes|hotwords|note-add|note-photo|source-.+)$/);
  for(const id of ['settings','about','update','keys','music','review','search','sidebar']) assert.equal(menu.snapshot()[id].enabled,false,id);
});
