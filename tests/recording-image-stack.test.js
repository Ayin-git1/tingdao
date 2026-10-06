const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8');
function load(name,context={}){
 const start=html.indexOf(`function ${name}(`);assert.ok(start>=0,`${name} exists`);
 const ctx=vm.createContext(context);vm.runInContext(html.slice(html.slice(start-6,start)==='async '?start-6:start,html.indexOf('\n}',start)+2),ctx);return ctx[name];
}
test('collapsed pile caps visible thumbnails at seven and uses repeatable angles',()=>{
 const pose=load('recordingImagePose',{RECORDING_IMAGE_ANGLES:[0,-7,6,-11,9,-4,3]});
 const first=Array.from({length:11},(_,i)=>pose(i,11,false,4));
 assert.equal(first.filter(x=>x.visible).length,7);
 assert.deepEqual(first,Array.from({length:11},(_,i)=>pose(i,11,false,4)));
 assert.equal(new Set(first.slice(0,7).map(x=>x.angle)).size,7);
});
test('expanded images fill a chronological equal-spacing grid anchored at bottom right',()=>{
 const pose=load('recordingImagePose',{RECORDING_IMAGE_ANGLES:[0,-7,6,-11,9,-4,3]});
 const items=Array.from({length:10},(_,i)=>pose(i,10,true,4));
 assert.equal(items.every(x=>x.visible),true);
 assert.equal(items[1].x-items[0].x,102);assert.equal(items[4].y-items[0].y,102);
 assert.equal(items[9].y,0);
});
test('capture reads the visible timer immediately and includes the current recording id',()=>{
 const capture=load('recordingImageCapture',{recordingImageSessionId:'session', $:()=>({textContent:'12:34'})});
 assert.deepEqual(JSON.parse(JSON.stringify(capture())),{sid:'session',time:754,intent:{mode:'inline',position:'after',rowId:null}});
});
test('native recording drop uses the same captured-time upload path',()=>{
 const calls=[];const handler=load('handleRecordingNativeImageDrag',{
  state:'recording',view:null,recordingImageSessionId:'s',recordingImageNativePaths:[],
  transcriptNoteNativeImagePaths:p=>p,recordingImageCapture:()=>({time:5,sid:'s'}),
  setRecordingImageDropHint(){},insertTranscriptImageFiles:(...args)=>calls.push(args),$:()=>({classList:{toggle(){}}})
 });
 assert.equal(handler('drop',{paths:['/tmp/a.png']}),true);
 assert.equal(calls.length,1);assert.equal(calls[0][1].time,5);assert.equal(calls[0][2],true);
});
test('stop waits for in-flight images before asking the backend to finish',async()=>{
 let release;const upload=new Promise(resolve=>{release=resolve;});const calls=[];
 const button={disabled:false};const ctx=vm.createContext({
  recordingImageStopping:false,recordingImageUploads:new Set([upload]),sessionName:'',
  $:id=>id==='stopConfirm'?button:id==='stopmodal'?{classList:{remove(){}}}:{value:''},
  api:async path=>{calls.push(path);return {};}
 });
 const start=html.indexOf("$('stopConfirm').onclick = async ()=>{");
 const code=html.slice(start,html.indexOf('\n};',start)+3);
 vm.runInContext(code,ctx);const stopping=button.onclick();
 assert.equal(calls.length,0);assert.equal(button.disabled,true);
 release();await stopping;assert.deepEqual(calls,['/api/stop']);assert.equal(button.disabled,false);
});
test('status hydration reconciles an optimistic image without a duplicate',()=>{
 const item={asset:'asset',file:null,card:{classList:{remove(){}},querySelector:()=>({})}};const added=[];
 const sync=load('syncRecordingImages',{recordingImageDeletedFiles:new Set(),recordingImageSessionId:'s',recordingImages:[item],state:'recording',addRecordingImage:(...args)=>added.push(args)});
 sync([{asset:'asset',file:'note-images/a.png',t:5},{asset:'other',file:'note-images/b.png',t:6}],'s');
 assert.equal(item.file,'note-images/a.png');assert.equal(added.length,1);
});

test('card motion uses bounded easing without spring keyframes',()=>{
 const animations=[];const card={style:{},getAnimations:()=>[],animate:(frames,options)=>animations.push({frames,options})};
 const animate=load('animateRecordingImage',{RECORDING_IMAGE_FADE_DELAY:360,window:{matchMedia:()=>({matches:false})},
  getComputedStyle:()=>({transform:'none',opacity:'1'}),DOMMatrix:class{constructor(){this.m41=0;this.m42=0;this.m12=0;this.m11=1;}}});
 animate({card},{x:-204,y:-102,angle:0,visible:true});
 assert.ok(animations[0].frames.length<=3);
 assert.equal(animations[0].options.easing,'cubic-bezier(.22,1,.36,1)');
});
test('after deletion the grid closes after 650ms only if the pointer stays outside',()=>{
 let callback,delay,inside=false;const closed=[];
 const schedule=load('scheduleRecordingImageClose',{recordingImageCloseTimer:null,recordingImageDeleteGrace:true,
  clearTimeout(){},setTimeout:(fn,ms)=>{callback=fn;delay=ms;return 1;},
  recordingImagePointerInside:()=>inside,expandRecordingImages:value=>closed.push(value),
  $:()=>({contains:()=>false}),document:{activeElement:null}});
 schedule();assert.equal(delay,650);inside=true;callback();assert.deepEqual(closed,[]);
 schedule();inside=false;callback();assert.deepEqual(closed,[false]);
});
test('overflow fades follow the directional delay and preserve interrupted opacity',()=>{
 for(const visible of [true,false]){
  const animations=[];const card={style:{},getAnimations:()=>[],animate:(frames,options)=>animations.push({frames,options})};
  const animate=load('animateRecordingImage',{window:{matchMedia:()=>({matches:false})},
   recordingImageExpanded:visible,$:()=>({getBoundingClientRect:()=>({right:500,bottom:500})}),
   getComputedStyle:()=>({transform:'none',opacity:'.4'}),DOMMatrix:class{constructor(){this.m41=0;this.m42=0;this.m12=0;this.m11=1;}}});
  animate({card,extraFade:visible},{x:0,y:0,angle:0,visible},visible?160:0,false,{x:420,y:410,angle:0,opacity:.4});
  assert.equal(animations[0].options.delay,visible?160:0);
  assert.equal(animations[0].frames[0].opacity,.4);
  assert.equal(animations[0].frames[1].opacity,visible?1:0);
  if(visible)assert.notEqual(animations[0].frames[0].transform,animations[0].frames[1].transform);
 }
});
test('layout fades extras before gathering and reveals extras after spreading',()=>{
 for(const expanded of [true,false]){
  const calls=[];const elements={};
  const items=Array.from({length:9},()=>({file:'a',card:{style:{},
   getBoundingClientRect:()=>({left:10,top:20,width:86,height:86}),
   classList:{toggle(){}},querySelector:()=>({})}}));
  const layout=load('layoutRecordingImages',{recordingImages:items,recordingImageExpanded:expanded,recordingImageLayoutVersion:0,
   RECORDING_IMAGE_FADE_DELAY:160,innerWidth:1000,view:null,state:'recording',
   $:id=>elements[id]||(elements[id]={style:{},classList:{toggle(){}},getAnimations:()=>[],animate(){}}),
   getComputedStyle:()=>({transform:'none',opacity:'.6'}),
   DOMMatrix:class{constructor(){this.m12=0;this.m11=1;}},
   recordingImagePose:()=>({visible:true}),animateRecordingImage:(...args)=>calls.push(args),
   recordingImagePointerInside:()=>true});
  layout();
  assert.equal(calls[0][2],expanded?0:140);
  assert.equal(calls[7][2],expanded?160:0);
  assert.equal(calls[8][2],expanded?184:0);
  assert.equal(calls[0][4].opacity,.6);
  assert.deepEqual(items.slice(0,7).map(item=>item.card.style.zIndex),['8','7','6','5','4','3','2']);
 }
});

test('deleting a card shrinks and fades before removing it and filling the gap',async()=>{
 let finish;const frames=[];let removed=false,laidOut=false;
 const item={card:{style:{},getAnimations:()=>[],contains:()=>false,remove:()=>{removed=true;},
  animate:(keys,options)=>{frames.push({keys,options});return {finished:new Promise(resolve=>{finish=resolve;})};}}};
 const remove=load('removeRecordingImage',{recordingImages:[item],window:{matchMedia:()=>({matches:false})},
  getComputedStyle:()=>({transform:'none',opacity:'1'}),$:()=>({}),layoutRecordingImages:()=>{laidOut=true;}});
 const pending=remove(item,true);assert.equal(removed,false);assert.equal(laidOut,false);
 assert.equal(frames[0].keys[1].opacity,0);assert.match(frames[0].keys[1].transform,/scale\(\.65\)/);
 finish();await pending;assert.equal(removed,true);assert.equal(laidOut,true);
});

test('count finishes fading in just before the return timeline ends',()=>{
 for(const [expanded,listTransition] of [[false,true],[true,true],[false,false]]){
  const elements={},badges=[];let cancelled=0;
  const item={file:'a',card:{style:{},getBoundingClientRect:()=>({left:0,top:0,width:86,height:86}),
   classList:{toggle(){}},querySelector:()=>({})}};
  const count={style:{visibility:'hidden'},getAnimations:()=>[{cancel:()=>cancelled++}],
   animate:(frames,options)=>badges.push({frames,options})};
  const layout=load('layoutRecordingImages',{recordingImages:Array(8).fill(item),recordingImageExpanded:expanded,
   recordingImageLayoutVersion:0,RECORDING_IMAGE_FADE_DELAY:160,innerWidth:1000,view:null,state:'recording',
   $:id=>id==='recordingImageCount'?count:elements[id]||(elements[id]={style:{},classList:{toggle(){}},getAnimations:()=>[],animate(){}}),
   getComputedStyle:()=>({transform:'none',opacity:'1'}),DOMMatrix:class{constructor(){this.m12=0;this.m11=1;}},
   recordingImagePose:()=>({visible:true}),
   animateRecordingImage:(_item,_pose,delay)=>({effect:{getComputedTiming:()=>({endTime:delay+460})}}),
   recordingImagePointerInside:()=>true});
  layout(null,listTransition);assert.equal(count.style.visibility,'');assert.equal(cancelled,1);
  if(expanded||!listTransition)assert.equal(badges.length,0);
  else{
   assert.equal(badges.length,1);assert.equal(badges[0].options.delay,572);
   assert.equal(badges[0].options.delay+badges[0].options.duration,692);
   assert.equal(badges[0].options.fill,'backwards');
   assert.equal(badges[0].frames[0].opacity,0);assert.equal(badges[0].frames[1].opacity,1);
  }
 }
});

test('delayed unfolding retains the live tilt rather than snapping to the grid angle',()=>{
 const animations=[];const card={style:{},getAnimations:()=>[],animate:(frames,options)=>{animations.push({frames,options});return {};}};
 const animate=load('animateRecordingImage',{recordingImageExpanded:true,
  window:{matchMedia:()=>({matches:false})},$:()=>({getBoundingClientRect:()=>({right:500,bottom:500})}),
  getComputedStyle:()=>({transform:'none',opacity:'1'}),
  DOMMatrix:class{constructor(){this.m41=0;this.m42=0;this.m12=0;this.m11=1;}}});
 animate({card},{x:-102,y:-102,angle:.5,visible:true},132,false,{x:420,y:410,angle:-11,opacity:1});
 assert.match(animations[0].frames[0].transform,/rotate\(-11deg\)/);
 assert.match(animations[0].frames[1].transform,/rotate\(0\.5deg\)/);
 assert.equal(animations[0].options.fill,'backwards');
 assert.equal(animations[0].options.delay,132);
});

test('ordinary pointer departure closes immediately without a deletion grace timer',()=>{
 const closed=[];let waits=0;
 const schedule=load('scheduleRecordingImageClose',{recordingImageCloseTimer:null,recordingImageDeleteGrace:false,
  clearTimeout(){},setTimeout:()=>{waits++;},recordingImagePointerInside:()=>false,
  expandRecordingImages:value=>closed.push(value),$:()=>({contains:()=>false}),document:{activeElement:null}});
 schedule();assert.equal(waits,0);assert.deepEqual(closed,[false]);
});
