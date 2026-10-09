const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const html=fs.readFileSync('index.html','utf8');
function harness(){
 const inserted=[];
 const rows=[[-100,0,5],[100,200,40],[260,440,120],[550,650,200]].map(([top,bottom,t],i)=>({dataset:{t:String(t),rowId:`segment-${i}`},getBoundingClientRect:()=>({top,bottom})}));
 const wrap={getClientRects:()=>[{}],getBoundingClientRect:()=>({top:0,bottom:600,height:600})};
 const ctx=vm.createContext({recordingImageCapture:()=>({sid:'session',time:5,intent:{mode:'inline'}}),state:'idle',view:{id:'project'},window:{innerHeight:800},document:{querySelector:()=>null},
  $:id=>id==='feedwrap'?wrap:id==='transcriptNoteLayer'?{hidden:true}:{querySelectorAll:()=>rows},
  transcriptNoteImageFiles:data=>data.files||[],insertTranscriptImageFiles:(files,target)=>inserted.push({files,target})});
 for(const name of ['transcriptVisibleImagePasteTarget','handleTranscriptImagePaste']){
  const start=html.indexOf(`function ${name}(`);assert.ok(start>=0,name);
  vm.runInContext(html.slice(start,html.indexOf('\n}',start)+2),ctx);
 }
 const event={target:{closest:()=>null},clipboardData:{files:[{name:'a.png'}]},preventDefault(){this.prevented=true;}};
 return {ctx,inserted,event,wrap,rows};
}
test('paste inserts after the screen-center paragraph independently of playback',()=>{
 const {ctx,event,inserted}=harness();ctx.player={currentTime:5};ctx.handleTranscriptImagePaste(event);
 assert.equal(inserted.length,1);assert.equal(inserted[0].target.time,120);
 assert.equal(inserted[0].target.intent.rowId,'segment-2');assert.equal(inserted[0].target.intent.position,'after');
 assert.equal(inserted[0].target.intent.mode,'inline');assert.equal(event.prevented,true);
});
test('scrolling changes the insertion paragraph even while playback stays fixed',()=>{
 const {ctx,event,inserted,rows}=harness();ctx.player={currentTime:5};
 rows[2].getBoundingClientRect=()=>({top:-200,bottom:-50});rows[3].getBoundingClientRect=()=>({top:250,bottom:350});
 ctx.handleTranscriptImagePaste(event);assert.equal(inserted[0].target.time,200);
});
test('home, hidden manuscript, editors, dialogs and text-only paste do not insert images',()=>{
 for(const mode of ['home','hidden','editor','dialog','text','handled']){
  const {ctx,event,inserted,wrap}=harness();
  if(mode==='home')ctx.view=null;
  if(mode==='hidden')wrap.getClientRects=()=>[];
  if(mode==='editor')event.target.closest=()=>({});
  if(mode==='dialog')ctx.document.querySelector=()=>({});
  if(mode==='text')event.clipboardData.files=[];
  if(mode==='handled')event.defaultPrevented=true;
  ctx.handleTranscriptImagePaste(event);assert.equal(inserted.length,0,mode);assert.equal(event.prevented,undefined,mode);
 }
});

test('recording and paused paste work without an opened history document',()=>{
 for(const state of ['recording','paused']){
  const {ctx,event,inserted}=harness();ctx.state=state;ctx.view=null;
  ctx.handleTranscriptImagePaste(event);assert.equal(inserted.length,1);assert.equal(inserted[0].target.intent.mode,'inline');
 }
});

test('recording locks image targets, resize and layout persistence',async()=>{
 const ctx=vm.createContext({state:'recording'});
 for(const name of ['transcriptMainImageTarget','startTranscriptMainImageResize','persistTranscriptMainImageNode']){
  const start=html.indexOf(`function ${name}(`);
  vm.runInContext(html.slice(name.startsWith('persist')?start-6:start,html.indexOf('\n}',start)+2),ctx);
 }
 for(const state of ['recording','paused','stopping']){
  ctx.state=state;
  assert.equal(ctx.transcriptMainImageTarget({}),null);
  assert.equal(ctx.startTranscriptMainImageResize({button:0},{}),undefined);
  assert.equal(await ctx.persistTranscriptMainImageNode({},{}),false);
 }
});
test('live image upload captures time, shows pending preview and marks it saved',async()=>{
 const calls=[];const previews=[];const ctx=vm.createContext({recordingImageUploads:new Set(),recordingImageStopping:false,state:'recording',view:null,recordingImageSessionId:'session',
  recordingImageCapture:()=>({sid:'session',time:5,intent:{mode:'inline'}}),
  addRecordingImage:(record,capture)=>{const item={capture,card:{classList:{remove(){}},querySelector:()=>({})}};previews.push(item);return item;},removeRecordingImage(){},
  transcriptNoteReadFile:async()=>({id:'asset',name:'a.png',mime:'image/png',width:640,height:480}),
  api:async(path,body)=>{calls.push({path,body});return {ok:true,note:{content:[{type:'image',file:'note-images/a.png'}]}};},refreshHistory(){},toast(){}});
 const start=html.indexOf('async function insertTranscriptImageFiles(');
 vm.runInContext(html.slice(start,html.indexOf('\n}',start)+2),ctx);
 await ctx.insertTranscriptImageFiles([{}],{intent:{mode:'inline'}});
 assert.equal(calls[0].path,'/api/note');assert.equal(calls[0].body.content[0].layout,'inline');
 assert.equal(calls[0].body.t,5);assert.equal(calls[0].body.id,'session');
 assert.equal(previews.length,1);assert.equal(previews[0].file,'note-images/a.png');
});

test('a closed recording note cannot intercept timeline image paste through a stale event target',()=>{
 for(const state of ['recording','paused']){
  const {ctx,event,inserted}=harness();ctx.state=state;ctx.view=null;
  const noteInput={closest:()=>noteInput};const lookup=ctx.$;
  ctx.$=id=>id==='noteInput'?noteInput:lookup(id);
  ctx.notePopOpen=()=>false;event.target=noteInput;
  ctx.handleTranscriptImagePaste(event);
  assert.equal(inserted.length,1,state);assert.equal(event.prevented,true);
  assert.equal(inserted[0].target.time,5);
 }
});

test('an open recording note retains its own text editing and cannot paste timeline images',()=>{
 const {ctx,event,inserted}=harness();ctx.state='recording';ctx.view=null;
 const noteInput={closest:()=>noteInput};const lookup=ctx.$;
 ctx.$=id=>id==='noteInput'?noteInput:lookup(id);
 ctx.notePopOpen=()=>true;event.target=noteInput;
 ctx.handleTranscriptImagePaste(event);
 assert.equal(inserted.length,0);assert.equal(event.prevented,undefined);
});

test('closing recording notes releases its focus without moving focus from other controls',()=>{
 const start=html.indexOf('function hideNotePop(');
 for(const focused of [true,false]){
  let blurred=0;const input={value:'draft',blur(){blurred++;}};
  const ctx=vm.createContext({document:{activeElement:focused?input:{}},growNote(){},
   $:id=>id==='noteInput'?input:{classList:{remove(){}},style:{}}});
  vm.runInContext(html.slice(start,html.indexOf('\n}',start)+2),ctx);
  ctx.hideNotePop();assert.equal(blurred,focused?1:0);assert.equal(input.value,'');
 }
});
