const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');const start=html.indexOf('const noteImagePreloads=new Map();');const source=html.slice(start,html.indexOf('\nasync function loadSession',start));
test('reentering a project reuses decoded images and preserves URL escaping',async()=>{
 const images=[];const context=vm.createContext({Image:class{constructor(){images.push(this);}decode(){return Promise.resolve();}}});
 vm.runInContext(source,context);
 const session={id:'a b',notes:[{content:[{type:'image',file:'note-images/a b.png'},{type:'image',file:'note-images/a b.png'}]}]};
 await context.preloadNoteImages(session);await context.preloadNoteImages(session);
 assert.equal(images.length,1);assert.equal(images[0].src,'/note-image/a%20b/a%20b.png');
});
test('broken images do not block entry and may retry later',async()=>{
 let attempts=0;const context=vm.createContext({Image:class{decode(){attempts++;return Promise.reject(new Error('missing'));}}});vm.runInContext(source,context);
 const session={id:'test',notes:[{content:[{type:'image',file:'missing.png'}]}]};
 await context.preloadNoteImages(session);await context.preloadNoteImages(session);assert.equal(attempts,2);
});

function sessionHarness(){
 const images=[],rendered=[],elements=new Map();
 const context=vm.createContext({
  Image:class{constructor(){images.push(this);}decode(){return new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject;});}},
  $:id=>{if(!elements.has(id))elements.set(id,{style:{},classList:{add(){},remove(){}}});return elements.get(id);},
  api:async path=>({id:path.split('/').pop(),name:'稿件',segments:[{t:0,text:'正文'}],notes:[{content:[{type:'image',file:'slow.png'}]}]}),
  transcriptViewGeneration:0,view:null,posDirty:false,RATES:['1'],defaultRateIdx:0,spkOrder:[],player:{},
  closeAllNotes(){},hideTranscriptImageDropIndicator(){},applyRate(){},hideResume(){},setConfirm(){},
  buildSpkOrder(){},updateNoteBtn(){},resetPlaybackSegments(){},
  transcriptContentItems:segments=>segments.map(segment=>({...segment,type:'seg'})),
  addSeg:segment=>rendered.push(segment.text),renderTimelineNotes(){},clearPlayerSource(){},
  renderTranscriptAnchors(){},drawerOpen:()=>false,refreshHistory(){},updateChrome(){},animateNotesEntry(){},
  fetchStatus:()=>Promise.resolve({}),syncJobs(){},updateRefineUI(){},toast(){},
 });
 vm.runInContext(source+html.slice(html.indexOf('async function loadSession('),html.indexOf('\nfunction exitView()')),context);
 return {context,images,rendered,elements};
}

test('正文与后续项目显示不等待图片解码，旧图片完成也不会切回旧项目',async()=>{
 const {context,images,rendered,elements}=sessionHarness();
 let completed=false;
 const first=context.loadSession('first').then(()=>{completed=true;});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(completed,true,'pending decode must not hold session entry');
 await first;
 assert.equal(context.view.id,'first');
 assert.deepEqual(rendered,['正文']);
 assert.equal(elements.get('feed').style.display,'block');
 await context.loadSession('second');
 assert.equal(context.view.id,'second');
 images[0].resolve();images[1].reject(new Error('missing'));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(context.view.id,'second');
 assert.deepEqual(rendered,['正文','正文']);
});
