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

function sessionHarness(duration=0){
 const images=[],rendered=[],elements=new Map();
 const context=vm.createContext({
  Image:class{constructor(){images.push(this);}decode(){return new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject;});}},
  $:id=>{if(!elements.has(id))elements.set(id,{style:{},classList:{add(){},remove(){},toggle(){}},setAttribute(k,v){this[k]=v;},appendChild(){},querySelector(){return {};}});return elements.get(id);},
  appendTranscriptItems(items,isCurrent,done){items.forEach(item=>rendered.push(item.text));return Promise.resolve(done()).then(()=>isCurrent());},
  api:async path=>({id:path.split('/').pop(),name:'稿件',duration,segments:[{t:0,text:'正文'}],notes:[{content:[{type:'image',file:'slow.png'}]}]}),
  requestAnimationFrame:fn=>setImmediate(fn),setTimeout,
  lastHistRaw:[],animateSidebarSelectionIn(){},
  TRANSCRIPT_LAZY_PAINT_MIN:300,transcriptViewGeneration:0,view:null,posDirty:false,RATES:['1'],defaultRateIdx:0,spkOrder:[],player:{},
  hideTranscriptFormatTools(){},resetTranscriptNoteLayer(){},editBarOff(){},closeAllNotes(){},hideTranscriptImageDropIndicator(){},applyRate(){},hideResume(){},setConfirm(){},
  buildSpkOrder(){},updateNoteBtn(){},resetPlaybackSegments(){},
  transcriptContentItems:segments=>segments.map(segment=>({...segment,type:'seg'})),
  addSeg:segment=>rendered.push(segment.text),renderTimelineNotes(){},clearPlayerSource(){},
  renderTranscriptAnchors(){},drawerOpen:()=>false,refreshHistory(){},updateChrome(){},animateNotesEntry(){},
  exitView(){},fetchStatus:()=>Promise.resolve({}),syncJobs(){},updateRefineUI(){},toast(){},
 });
 vm.runInContext(source+html.slice(html.indexOf('async function loadSession('),html.indexOf('\nfunction exitView()')),context);
 context.waitForSidebarEntryMotion=()=>context.nextTranscriptPaint();
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


test('long manuscripts show the mask before building and reveal only after completion',async()=>{
 const {context:c,elements,rendered}=sessionHarness(7201);
 let finish;const frames=[];c.requestAnimationFrame=fn=>frames.push(fn);
 c.appendTranscriptItems=(items,isCurrent,done)=>new Promise(resolve=>{finish=async()=>{rendered.push('built');await done();resolve(isCurrent());};});
 const loading=c.loadSession('long');await new Promise(resolve=>setImmediate(resolve));
 assert.equal(elements.get('transcriptLoading').hidden,false);assert.deepEqual(rendered,[]);
 frames.shift()();await new Promise(resolve=>setTimeout(resolve,5));
 assert.equal(typeof finish,'function');assert.equal(elements.get('transcriptLoading').hidden,false);
 await finish();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(elements.get('transcriptLoading').hidden,false,'the last batch must paint before reveal');
 frames.shift()();await loading;assert.equal(elements.get('transcriptLoading').hidden,true);
});
test('switching from a loading manuscript to a short one clears the mask and cancels old work',async()=>{
 const {context:c,elements,rendered}=sessionHarness(7201);const frames=[];c.requestAnimationFrame=fn=>frames.push(fn);
 const first=c.loadSession('long');await new Promise(resolve=>setImmediate(resolve));
 assert.equal(elements.get('transcriptLoading').hidden,false);
 c.api=async()=>({id:'short',name:'短稿',duration:7200,segments:[{t:0,text:'短稿正文'}],notes:[]});
 await c.loadSession('short');assert.equal(elements.get('transcriptLoading').hidden,true);
 frames.shift()();await first;assert.equal(c.view.id,'short');assert.deepEqual(rendered,['短稿正文']);
});

test('a two-hour manuscript never schedules a loading frame',async()=>{
 const {context:c,elements}=sessionHarness(7200),frames=[];c.requestAnimationFrame=fn=>frames.push(fn);
 await c.loadSession('two-hours');assert.equal(frames.length,0);assert.equal(elements.get('transcriptLoading').hidden,true);
});
test('a failed long manuscript render always releases the mask',async()=>{
 const {context:c,elements}=sessionHarness(7201),messages=[];c.toast=message=>messages.push(message);
 c.appendTranscriptItems=()=>Promise.reject(new Error('render failed'));
 await c.loadSession('broken');assert.equal(elements.get('transcriptLoading').hidden,true);assert.equal(messages.length,1);
});

test('known long manuscript shows its title and mask before requesting or constructing text',async()=>{
 const {context:c,elements,rendered}=sessionHarness(7201);let release,requests=0;
 c.lastHistRaw=[{id:'long',name:'新长稿标题',duration:7201}];
 c.waitForSidebarEntryMotion=()=>new Promise(resolve=>release=resolve);
 c.api=()=>{requests++;throw new Error('must not request during animation');};
 const pending=c.loadSession('long');
 assert.equal(c.view.id,'long');assert.equal(elements.get('nameInput').value,'新长稿标题');
 assert.equal(elements.get('transcriptLoading').hidden,false);assert.equal(elements.get('nameInput').readOnly,true);
 assert.equal(requests,0);assert.deepEqual(rendered,[]);
 c.transcriptViewGeneration++;c.view=null;c.setTranscriptLoading(false);release();await pending;
 assert.equal(requests,0);assert.equal(elements.get('transcriptLoading').hidden,true);
});
