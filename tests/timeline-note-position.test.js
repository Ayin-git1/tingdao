const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const html=fs.readFileSync('index.html','utf8');
for(const editing of [false,true])test(`fractional row time stays below its paragraph after ${editing?'editing':'adding'} a note`,async()=>{
  const controls={};
  const $=id=>controls[id]||(controls[id]={value:'',classList:{remove(){},add(){}},querySelector(){return null;},removeEventListener(){},addEventListener(){},focus(){}});
  $('transcriptNoteLayer').querySelector=()=>$('card');
  const row={isConnected:true,dataset:{rowId:'segment-0'},after(){}};
  let posted;
  const context=vm.createContext({$,view:{id:'test',duration:60,notes:[{t:12.8,text:'old'}]},
    transcriptNoteTargetRow:row,transcriptNoteCloseEnd:null,transcriptNoteTargetTime:0,
    transcriptNoteDuration:0,transcriptNoteEditingIndex:null,transcriptNoteOriginal:null,
    fmt:t=>`00:${String(Math.floor(t)).padStart(2,'0')}`,Map,
    setTranscriptNoteQuote(){},renderTranscriptNoteContent(){},hideTranscriptNoteMenu(){},
    refreshTranscriptImageAsideFlow(){},fitTranscriptNoteLayer(){},requestAnimationFrame(){},
    serializeTranscriptNoteContent:()=>({text:'note',content:[],assets:[]}),
    api:async(path,payload)=>{posted=payload;return {notes:[]};},renderTimelineNotes(){},
    closeTranscriptNote(){},refreshHistory(){},toast(){},animateTranscriptNoteRow(){}});
  vm.runInContext(html.slice(html.indexOf('function parseTranscriptNoteTime('),html.indexOf('function resetTranscriptNoteLayer(')),context);
  vm.runInContext(html.slice(html.indexOf("$('transcriptNoteSave').onclick=async()=>{"),html.indexOf("let copyMenuPurpose =")),context);
  context.openTranscriptNote(12.8,editing?0:null);
  await $('transcriptNoteSave').onclick();
  assert.equal(posted.t,12.8);
  if(!editing)assert.equal(posted.anchorRowId,'segment-0');
  assert.equal([{t:12.8},{t:20}].findIndex(row=>row.t>posted.t),1,'note must follow the selected paragraph');
});
test('saved paragraph anchor takes priority over an earlier timestamp during rendering',async()=>{
  const rows=[{dataset:{t:'350.8'}},{dataset:{t:'359'}}];
  const inserted=[];
  const feed={querySelectorAll:selector=>selector==='.seg:not(.sum)'?rows:[],
    insertBefore:(note,next)=>inserted.push({note,next}),querySelector:()=>rows[0],style:{}};
  const controls={feed,empty:{style:{}},allNotesPop:{hidden:true}};
  const context=vm.createContext({$:id=>controls[id],view:{notes:[{t:350,text:'1',anchorRowId:'segment-0'}]},
    clearImageDropPreview(){},resetImageAsideFlow(){},createNoteDom:()=>({}),Map});
  vm.runInContext(html.slice(html.indexOf('async function renderTimelineNotes('),html.indexOf('function applyStatus(')),context);
  await context.renderTimelineNotes();
  assert.equal(inserted[0].next,rows[1],'note must be inserted after its anchor even when its timestamp is earlier');
});
test('note mutations animate opening and closing, with reduced motion support',async()=>{
  const calls=[];
  const row={offsetHeight:48,animate:(frames,options)=>{calls.push({frames,options});return {finished:Promise.resolve(),cancel(){}};}};
  let reduced=false;
  const context=vm.createContext({matchMedia:()=>({matches:reduced})});
  const start=html.indexOf('async function animateTranscriptNoteRow(');
  assert.ok(start>=0,'note animation helper must exist');
  vm.runInContext(html.slice(start,html.indexOf('function parseTranscriptNoteTime(',start)),context);
  await context.animateTranscriptNoteRow(row,true);
  await context.animateTranscriptNoteRow(row,false);
  for(const call of calls)for(const frame of call.frames){
    assert.equal(frame.height,undefined,'note animation must not push the manuscript by changing height');
    assert.equal(frame.overflow,undefined,'animation must not clip note text');
  }
  assert.equal(calls[0].options.direction,'normal');
  assert.equal(calls[1].options.direction,'reverse');
  reduced=true;
  await context.animateTranscriptNoteRow(row,true);
  assert.equal(calls.length,2,'reduced motion skips the movement');
});

test('successful save removes composer before rendering the final note',()=>{
  const save=html.slice(html.indexOf("$('transcriptNoteSave').onclick=async()=>{"),html.indexOf('let copyMenuPurpose ='));
  assert.ok(save.indexOf('closeTranscriptNote(true)')>=0,'save must close the composer immediately');
  assert.ok(save.indexOf('closeTranscriptNote(true)')<save.indexOf('await renderTimelineNotes()'),'composer and final note must never occupy space together');
});
