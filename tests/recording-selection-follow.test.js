const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html','utf8');

test('live transcription cannot scroll or measure the transcript during a drag or while text is selected',()=>{
  let reads=0;
  const scrolls=[];
  const wrap={get clientHeight(){reads++;return 100;},scrollTop:0,scrollTo:options=>scrolls.push(options),
    style:{getPropertyValue:()=>'',setProperty(){},removeProperty(){}}};
  const textNode={}, feed={contains:node=>node===textNode,offsetTop:0,offsetHeight:500};
  const selection={isCollapsed:true,anchorNode:null,focusNode:null};
  const ctx=vm.createContext({state:'recording',view:null,userScrolling:false,transcriptSelectionPointer:{},
    window:{getSelection:()=>selection},matchMedia:()=>({matches:false}),$:id=>id==='feedwrap'?wrap:feed});
  for(const name of ['anchorLive','transcriptSelectionInProgress']){
    vm.runInContext(html.match(new RegExp('function '+name+'\\(\\)\\{[^]*?\\n\\}'))[0],ctx);
  }
  ctx.anchorLive();
  ctx.transcriptSelectionPointer=null;
  selection.isCollapsed=false;selection.focusNode=textNode;
  ctx.anchorLive();
  assert.equal(reads,0);
  assert.deepEqual(scrolls,[]);
  selection.isCollapsed=true;
  ctx.anchorLive();
  assert.equal(scrolls[0].top,438);
});
