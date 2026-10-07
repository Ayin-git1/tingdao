const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
function body(name){return html.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`))[0];}
test('double click cancels pending playback; single click still seeks', ()=>{
  let pending, seeks=0;
  const ctx={clearTimeout:()=>{pending=null;},setTimeout:fn=>{pending=fn;return 1;},player:{getAttribute:()=> 'audio.mp3'},seekTo:()=>seeks++};
  vm.createContext(ctx);vm.runInContext('let segmentPlaybackTimer=null;'+body('queueSegmentPlayback'),ctx);
  const row={dataset:{},isConnected:true};
  const click=detail=>ctx.queueSegmentPlayback({detail,target:{closest:()=>null}},row,12);
  click(1);assert.equal(seeks,0);click(2);assert.equal(pending,null);assert.equal(seeks,0);
  click(1);pending();assert.equal(seeks,1);
  row.dataset.edit='1';click(1);assert.equal(pending,null);
});
test('last-row result scrolls above audio and adds enough trailing space', ()=>{
  let padding, scroll;
  const bar={classList:{contains:()=>true},style:{},getBoundingClientRect:()=>({top:660,bottom:760})};
  const wrap={scrollTop:400,style:{setProperty:(key,value)=>padding=value},getBoundingClientRect:()=>({top:100,bottom:800}),scrollTo:value=>scroll=value};
  const audio={getClientRects:()=>[1],getBoundingClientRect:()=>({top:700,bottom:755})};
  const dock={getClientRects:()=>[]};
  const ctx={$:id=>({editbar:bar,feedwrap:wrap,audiobar:audio,dockgrp:dock})[id],innerHeight:900,matchMedia:()=>({matches:false}),Math};
  vm.createContext(ctx);vm.runInContext(body('fitEditBar'),ctx);ctx.fitEditBar();
  assert.equal(padding,'116px');assert.equal(scroll.top,476);assert.equal(bar.style.maxHeight,'568px');
});
test('result displays full revised sentence without old-text comparison', ()=>{
  assert.match(html,/已改这句<\/span> <b>\$\{esc\(r.text\)\}<\/b>/);
  assert.doesNotMatch(html,/esc\(cut\(old\)\)/);
});
test('note footer is scrolled above audio; editor shrinks in short viewports', ()=>{
  let padding, scroll;
  const editor={offsetHeight:220,style:{}};
  const card={getBoundingClientRect:()=>({top:400,bottom:720})};
  const layer={hidden:false,offsetHeight:300,querySelector:()=>card};
  const wrap={scrollTop:300,style:{setProperty:(key,value)=>padding=value},getBoundingClientRect:()=>({top:100,bottom:650}),scrollTo:value=>scroll=value};
  const audio={getClientRects:()=>[1],getBoundingClientRect:()=>({top:500,bottom:560})};
  const ctx={$:id=>({transcriptNoteLayer:layer,transcriptNoteText:editor,feedwrap:wrap,audiobar:audio,dockgrp:{getClientRects:()=>[]}})[id],innerHeight:700,matchMedia:()=>({matches:false}),Math};
  vm.createContext(ctx);vm.runInContext(body('fitTranscriptNoteLayer'),ctx);ctx.fitTranscriptNoteLayer();
  assert.equal(padding,'166px');assert.equal(scroll.top,536);
  assert.equal(editor.style.maxHeight,'288px');
  wrap.getBoundingClientRect=()=>({top:350,bottom:650});ctx.fitTranscriptNoteLayer();
  assert.equal(editor.style.minHeight,'38px');assert.equal(editor.style.maxHeight,'38px');
});
