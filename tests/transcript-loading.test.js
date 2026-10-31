const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function source(name){const match=html.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));assert.ok(match,`${name} exists`);return match[0];}
test('only manuscripts strictly longer than two hours use the loading phase',()=>{
 const c=vm.createContext({});vm.runInContext(source('transcriptNeedsLoading'),c);
 for(const duration of [undefined,0,7199,7200])assert.equal(c.transcriptNeedsLoading({duration}),false);
 assert.equal(c.transcriptNeedsLoading({duration:7201}),true);
 assert.equal(c.transcriptNeedsLoading({duration:7200,segments:Array(5000)}),false);
});
test('loading masks only the manuscript and clears interaction and accessibility state',()=>{
 const nodes=new Map();const classes=new Set();
 const c=vm.createContext({prepareTranscriptSkeleton(){},$:id=>{if(!nodes.has(id))nodes.set(id,{offsetTop:72,hidden:true,style:{},setAttribute(k,v){this[k]=v;},classList:{remove(k){classes.delete(k);},toggle(k,on){on?classes.add(k):classes.delete(k);}}});return nodes.get(id);}});
 vm.runInContext(source('setTranscriptLoading'),c);
 c.setTranscriptLoading(true);assert.equal(nodes.get('transcriptLoading').hidden,false);assert.equal(nodes.get('feed').inert,true);assert.equal(nodes.get('feed')['aria-busy'],'true');assert.ok(classes.has('transcript-loading'));
 c.setTranscriptLoading(false);assert.equal(nodes.get('transcriptLoading').hidden,true);assert.equal(nodes.get('feed').inert,false);assert.equal(nodes.get('feed')['aria-busy'],'false');assert.equal(classes.size,0);
});

test('sidebar transitions settle before the long-manuscript request starts',async()=>{
 const start=html.indexOf('async function loadSession('),end=html.indexOf('\nfunction exitView()',start);
 let releaseMotion,reply,requests=0;
 const c=vm.createContext({hideTranscriptFormatTools(){},transcriptViewGeneration:0,setTranscriptLoading(){},view:null,
 closeAllNotes(){},hideTranscriptImageDropIndicator(){},posDirty:false,lastHistRaw:[{id:'long',duration:7201}],
 showTranscriptLoadingPreview(){},transcriptNeedsLoading:d=>d.duration>7200,waitForSidebarEntryMotion:()=>new Promise(resolve=>releaseMotion=resolve),
 api:()=>{requests++;return new Promise(resolve=>reply=resolve);}});
 vm.runInContext(html.slice(start,end),c);const load=c.loadSession('long');
 assert.equal(requests,0,'session JSON must not compete with the selection transition');
 assert.equal(typeof releaseMotion,'function');c.transcriptViewGeneration++;releaseMotion();await load;
 assert.equal(requests,0,'a cancelled entry must not start a late request');
});

test('the entry gate waits for actual row transitions and ignores continuous animations',async()=>{
 let release;const finished=new Promise(resolve=>release=resolve);
 const c=vm.createContext({nextTranscriptPaint:()=>Promise.resolve(),$:()=>({getAnimations:()=>[
  {effect:{target:{classList:{contains:()=>true}},getComputedTiming:()=>({endTime:340})},finished},
  {effect:{target:{classList:{contains:()=>true}},getComputedTiming:()=>({endTime:Infinity})},finished:new Promise(()=>{})}
 ]})});
 const match=html.match(/async function waitForSidebarEntryMotion\([^]*?\n\}/);assert.ok(match);vm.runInContext(match[0],c);
 let done=false;const pending=c.waitForSidebarEntryMotion(()=>true).then(()=>done=true);
 await new Promise(resolve=>setImmediate(resolve));assert.equal(done,false);
 release();await pending;assert.equal(done,true);
});

test('skeleton sentences arrive in order with varied paragraph lengths and keep completed lines',()=>{
 const skeleton={innerHTML:''};
 const c=vm.createContext({$:()=>({querySelector:()=>skeleton}),Math:Object.assign(Object.create(Math),{random:()=>0.05})});
 vm.runInContext(source('prepareTranscriptSkeleton'),c);
 c.prepareTranscriptSkeleton();
 const short=skeleton.innerHTML;
 assert.equal((short.match(/class="line"/g)||[]).length,16);
 c.Math.random=()=>0.95;c.prepareTranscriptSkeleton();
 assert.equal((skeleton.innerHTML.match(/class="line"/g)||[]).length,32);
 assert.notEqual(short,skeleton.innerHTML);
 const delays=[...skeleton.innerHTML.matchAll(/class="line" style="[^"]*--delay:(\d+)ms/g)].map(m=>Number(m[1]));
 assert.equal(delays[0],0);
 for(let i=1;i<delays.length;i++)assert.ok(delays[i]>delays[i-1],'later sentences must appear after earlier ones');
 assert.match(html,/animation:skelWrite var\(--duration,35ms\) ease-out both paused/);
});
