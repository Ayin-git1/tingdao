const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function source(name){const m=html.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));assert.ok(m,name);return m[0];}
test('drag selection defers navigation layout reads until release',()=>{
 let reads=0,updates=0;
 const ctx={transcriptSelectionPointer:{x:10,y:10},transcriptAnchorState:[{}],segEls:[{}],player:{paused:true,ended:false},transcriptAnchorCanFollowScroll:()=>true,transcriptScrollTime:()=>{reads++;return 10;},transcriptAnchorIndex:()=>0,transcriptAnchorActiveIndex:0,updateTranscriptOutlineActive:()=>updates++,setTranscriptAnchorActiveIndex:()=>updates++};
 vm.createContext(ctx);vm.runInContext(source('updateTranscriptAnchorFromScroll'),ctx);
 for(let i=0;i<120;i++)ctx.updateTranscriptAnchorFromScroll();
 assert.equal(reads,0,'dragging must not measure layout on each scroll frame');
 ctx.transcriptSelectionPointer=null;ctx.updateTranscriptAnchorFromScroll();
 assert.equal(reads,1);assert.equal(updates,1);
});
test('drag selection defers reading-position hit testing until release',()=>{
 let hits=0;const ctx={transcriptSelectionPointer:{},transcriptReadingMark:null,$:()=>({querySelector:()=>true}),transcriptReadingAnchor:()=>{hits++;return {row:{}};}};
 vm.createContext(ctx);vm.runInContext(html.slice(html.indexOf('function markTranscriptReadingPosition(){'),html.indexOf('new ResizeObserver(()=>{',html.indexOf('function markTranscriptReadingPosition(){'))),ctx);
 for(let i=0;i<120;i++)ctx.markTranscriptReadingPosition();
 assert.equal(hits,0);ctx.transcriptSelectionPointer=null;ctx.markTranscriptReadingPosition();assert.equal(hits,1);
});
test('image bookmark scans pause during text dragging and resume on pointer release',()=>{
 const start=html.indexOf('  function refreshPreview(){'),end=html.indexOf('  function schedulePreview(){',start);
 let reads=0;const listeners={};
 const ctx={frame:1,transcriptSelectionPointer:{},wrap:{classList:{contains:()=>true},getBoundingClientRect(){reads++;return {height:0};}},document:{body:{classList:{contains:()=>false}},addEventListener(type,fn){listeners[type]=fn;}},preview:{},activeSource:null};
 vm.createContext(ctx);vm.runInContext(html.slice(start,end),ctx);
 for(let i=0;i<120;i++)ctx.refreshPreview();assert.equal(reads,0);
 ctx.transcriptSelectionPointer=null;ctx.refreshPreview();assert.equal(reads,1);
 assert.match(html.slice(end,html.indexOf("$('feedwrap').addEventListener('dragenter'",end)),/document\.addEventListener\('pointerup',schedulePreview\)/);
});
