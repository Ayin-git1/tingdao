const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const reload=html.slice(html.indexOf('async function reloadRefined('),html.indexOf('\nfunction handleEvent('));
test('delayed old refinement reload cannot replace a new recording view',async()=>{
 const timers=[],frames=[],feed={style:{}},wrap={scrollTop:25};let loads=0;
 const context=vm.createContext({view:{id:'old'},transcriptViewGeneration:0,$:id=>id==='feed'?feed:wrap,
 setTimeout:fn=>timers.push(fn),requestAnimationFrame:fn=>frames.push(fn),loadSession:async()=>{loads++;context.view={id:'old'};}});
 vm.runInContext(reload,context);const pending=context.reloadRefined('old');
 context.view=null;context.transcriptViewGeneration++;timers.shift()();await pending;
 assert.equal(loads,0);assert.equal(context.view,null);assert.equal(frames.length,0);
});
test('a late session HTTP response is discarded after recording entry',async()=>{
 let reply;const context=vm.createContext({view:{id:'old'},transcriptViewGeneration:0,posDirty:false,
 hideTranscriptFormatTools(){},resetTranscriptNoteLayer(){},closeAllNotes(){},hideTranscriptImageDropIndicator(){},api:()=>new Promise(resolve=>reply=resolve),
 preloadNoteImages(){throw new Error('stale response must not render');},toast(){}});
 const source=html.slice(html.indexOf('async function loadSession('),html.indexOf('\nfunction exitView()'));
 vm.runInContext(source,context);const pending=context.loadSession('old');
 context.view=null;context.transcriptViewGeneration++;reply({id:'old'});await pending;
 assert.equal(context.view,null);
});
test('refinement reload still runs when the user stays on the same manuscript',async()=>{
 const timers=[],frames=[],feed={style:{}},wrap={scrollTop:25};let loads=0;
 const context=vm.createContext({view:{id:'old'},transcriptViewGeneration:0,$:id=>id==='feed'?feed:wrap,
 setTimeout:fn=>timers.push(fn),requestAnimationFrame:fn=>frames.push(fn),loadSession:async()=>{loads++;context.transcriptViewGeneration++;wrap.scrollTop=0;}});
 vm.runInContext(reload,context);const pending=context.reloadRefined('old');timers.shift()();await pending;
 assert.equal(loads,1);assert.equal(wrap.scrollTop,25);frames.shift()();timers.shift()();assert.equal(feed.style.opacity,'');
});
const waitSource=html.slice(html.indexOf('async function waitForFinishThenLoad('),html.indexOf("\n$('btnPause').onclick",html.indexOf('async function waitForFinishThenLoad(')));
test('old stop waiter cannot apply idle status or open old project after a new recording starts',async()=>{
 let reply;const applied=[],loaded=[],messages=[];
 const context=vm.createContext({transcriptViewGeneration:0,fetchStatus:()=>new Promise(resolve=>reply=resolve),
 applyStatus:st=>applied.push(st),loadSession:async id=>loaded.push(id),toast:msg=>messages.push(msg),playCompletionSound(){},setTimeout(){}});
 vm.runInContext(waitSource,context);const pending=context.waitForFinishThenLoad('old');
 context.transcriptViewGeneration++;reply({state:'idle'});await pending;
 assert.deepEqual(applied,[]);assert.deepEqual(loaded,[]);assert.deepEqual(messages,[]);
});
test('current stop waiter still opens the saved project',async()=>{
 const loaded=[],applied=[];
 const context=vm.createContext({transcriptViewGeneration:0,fetchStatus:async()=>({state:'idle'}),
 applyStatus:st=>applied.push(st),loadSession:async id=>{context.transcriptViewGeneration++;loaded.push(id);},toast(){},playCompletionSound(){}});
 vm.runInContext(waitSource,context);await context.waitForFinishThenLoad('current');
 assert.equal(applied.length,1);assert.deepEqual(loaded,['current']);
});
