const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function harness(){
 const listeners={},frames=[];let selected=true,now=1000;const updates=[];
 const elements=Object.fromEntries(['feed','feedwrap','transcriptFormatTools'].map(id=>[id,{hidden:true,contains:()=>false,addEventListener(type,fn){listeners[id+':'+type]=fn;}}]));
 const ctx={$:id=>elements[id],document:{addEventListener(type,fn){(listeners[type]??=[]).push(fn);}},window:{addEventListener(){},getSelection:()=>({isCollapsed:!selected})},clearTimeout(){},hideTranscriptFormatTools(){},clearTranscriptTextSelection(){selected=false;},refreshTranscriptFormatSelection(){updates.push("format");},markTranscriptReadingPosition(){updates.push("reading");},updateTranscriptAnchorFromScroll(){updates.push("navigation");},requestAnimationFrame:fn=>frames.push(fn),Date:{now:()=>now},Math};
 vm.createContext(ctx);
 vm.runInContext('let segmentPlaybackTimer=null,transcriptSelectionDragUntil=0,transcriptFormatBusy=false;'+html.slice(html.indexOf('let transcriptSelectionPointer=null;'),html.indexOf('window.addEventListener(\'resize\',hideTranscriptFormatTools);')),ctx);
 const start=()=>listeners['feed:pointerdown']({target:{closest:()=>true},clientX:100,clientY:200});
 const move=(x=120,y=200)=>listeners.pointermove.forEach(fn=>fn({clientX:x,clientY:y}));
 const clickBlocked=()=>now<vm.runInContext('transcriptSelectionDragUntil',ctx);
 return {updates,move,clickBlocked,settle:()=>now+=651,start,scroll:()=>listeners['feedwrap:scroll'](),end:type=>listeners[type]?.forEach(fn=>fn()),selected:()=>selected,frames};
}
test('edge autoscroll preserves text selection throughout a drag',()=>{
 const h=harness();h.start();h.scroll();h.scroll();assert.equal(h.selected(),true);
});
test('ordinary scroll still clears selection after releasing the mouse',()=>{
 const h=harness();h.start();h.end('pointerup');h.settle();h.scroll();assert.equal(h.selected(),false);assert.equal(h.frames.length,1);
});
test('cancelled pointer does not leave selection dragging active',()=>{
 const h=harness();h.start();h.end('pointercancel');h.settle();h.scroll();assert.equal(h.selected(),false);
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
