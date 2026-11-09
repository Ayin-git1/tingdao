const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function harness(){
 const listeners={},frames=[];let selected=true,now=1000;const updates=[];
 const elements=Object.fromEntries(['feed','feedwrap','transcriptFormatTools'].map(id=>[id,{hidden:true,contains:()=>false,scrollTo(){},addEventListener(type,fn){listeners[id+':'+type]=fn;}}]));
 const ctx={$:id=>elements[id],document:{addEventListener(type,fn){(listeners[type]??=[]).push(fn);}},window:{addEventListener(){},getSelection:()=>({isCollapsed:!selected})},clearTimeout(){},engageTick(){},scrollFrameUpdate:fn=>()=>frames.push(fn),hideTranscriptFormatTools(){},clearTranscriptTextSelection(){selected=false;},refreshTranscriptFormatSelection(){updates.push("format");},markTranscriptReadingPosition(){updates.push("reading");},updateTranscriptAnchorFromScroll(){updates.push("navigation");},requestAnimationFrame:fn=>frames.push(fn),Date:{now:()=>now},Math};
 vm.createContext(ctx);
 vm.runInContext('let segmentPlaybackTimer=null,transcriptSelectionDragUntil=0,transcriptFormatBusy=false;'+html.slice(html.indexOf('let transcriptSelectionPointer=null;'),html.indexOf('window.addEventListener(\'resize\',hideTranscriptFormatTools);')),ctx);
 const start=()=>listeners['feed:pointerdown']({button:0,target:{closest:()=>true},clientX:100,clientY:200});
 const move=(x=120,y=200)=>listeners.pointermove.forEach(fn=>fn({clientX:x,clientY:y}));
 const clickBlocked=()=>now<vm.runInContext('transcriptSelectionDragUntil',ctx);
 return {updates,move,clickBlocked,settle:()=>now+=651,start,scroll:()=>listeners['feedwrap:scroll'](),end:type=>listeners[type]?.forEach(fn=>fn()),selected:()=>selected,pointer:()=>vm.runInContext('transcriptSelectionPointer',ctx),frames};
}
test('edge autoscroll preserves text selection throughout a drag',()=>{
 const h=harness();h.start();h.scroll();h.scroll();assert.equal(h.selected(),true);
});
test('ordinary scroll preserves selection after releasing the mouse',()=>{
 const h=harness();h.start();h.end('pointerup');h.settle();h.scroll();assert.equal(h.selected(),true);assert.equal(h.frames.length,1);
});
test('pointer cancellation releases gesture state without clearing native selection',()=>{
 const h=harness();h.start();h.end('pointercancel');h.settle();h.scroll();assert.equal(h.selected(),true);assert.equal(h.pointer(),null);
});

test('releasing a drag refreshes deferred navigation and tools on the next frame',()=>{
 const h=harness();h.start();h.scroll();h.end('pointerup');
 assert.deepEqual(h.updates,[]);h.frames.shift()();
 assert.deepEqual(h.updates,['reading','navigation','format']);assert.equal(h.selected(),true);
});

test('queued autoscroll after pointer release preserves the completed selection',()=>{
 const h=harness();h.start();h.move();h.end('pointerup');h.scroll();
 assert.equal(h.selected(),true);h.frames.shift()();assert.equal(h.selected(),true);
});

test('a plain click on transcript text is not treated as a drag',()=>{
 const h=harness();h.start();h.end('pointerup');assert.equal(h.clickBlocked(),false);
 h.frames.shift()();assert.deepEqual(h.updates,['reading','navigation','format']);
});

test('jitter below the drag threshold still counts as a click',()=>{
 const h=harness();h.start();h.move(102,201);h.end('pointerup');assert.equal(h.clickBlocked(),false);
});

test('a real drag blocks the click that follows its release',()=>{
 const h=harness();h.start();h.move();h.settle();h.end('pointerup');assert.equal(h.clickBlocked(),true);
});

function mouseSelectionHarness(){
 const source=html.match(/function installTranscriptMouseSelection\(\)\{[^]*?\n\}/);
 assert.ok(source,'a macOS transcript drag adapter is installed');
 const listeners={},frames=[],moves=[];
 const first={isConnected:true},last={isConnected:true};
 let stopCount=0,step,focus=first;
 const selection={isCollapsed:true,collapse(){this.isCollapsed=true;},
   setBaseAndExtent(...args){moves.push(args);this.isCollapsed=false;}};
 const feed={contains:node=>[first,last].includes(node),addEventListener(type,fn){listeners[type]=fn;}};
 const wrap={getBoundingClientRect:()=>({left:0,right:500,top:50,bottom:400})};
 const ctx={$:id=>id==='feed'?feed:wrap,transcriptSelectionPointer:{moved:true,mouse:true},window:{getSelection:()=>selection,addEventListener(){}},
   document:{caretRangeFromPoint:()=>({startContainer:focus,startOffset:2}),addEventListener(type,fn){listeners[type]=fn;}},
   scrollFrameUpdate:fn=>()=>frames.push(fn),requestAnimationFrame(){},cancelAnimationFrame(){},
   createSidebarAutoScroller(_wrap,_bounds,onStep){step=onStep;return {update(){},stop(){stopCount++;}};}};
 vm.runInNewContext(source[0]+'\ninstallTranscriptMouseSelection();',ctx);
 const point={clientX:125,clientY:425};
 const down=(options={})=>{
   let prevented=false;
   listeners.mousedown({button:0,detail:1,target:{closest:selector=>selector.startsWith('.seg')},
     preventDefault(){prevented=true;},...options});
   return prevented;
 };
 return {first,last,down,moves,move:()=>{focus=last;listeners.pointermove(point);},
   flush:()=>frames.shift()(),tick:()=>step(point),cancel:()=>listeners.pointercancel(),
   get stopCount(){return stopCount;}};
}
test('ordinary drag retains its anchor as scrolling moves the selection focus and cancels cleanly',()=>{
 const h=mouseSelectionHarness();
 assert.equal(h.down(),true);
 h.move();h.flush();h.tick();
 assert.deepEqual(h.moves.at(-1),[h.first,2,h.last,2]);
 h.cancel();const moves=h.moves.length;h.tick();
 assert.equal(h.moves.length,moves);assert.equal(h.stopCount,1);
});
test('double clicks and modified clicks stay on native selection',()=>{
 const h=mouseSelectionHarness();
 assert.equal(h.down({detail:2}),false);
 assert.equal(h.down({shiftKey:true}),false);
 assert.equal(h.down({metaKey:true}),false);
});
