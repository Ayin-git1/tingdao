const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function render(layout='inline',contentWidth=600){
  let reads=0;const inserted=[],asides=[];
  const rows=Array.from({length:4042},(_,i)=>({dataset:{t:i*8},classList:{add(){}},style:{setProperty(){}},
    querySelector:()=>({getBoundingClientRect(){reads++;return {width:contentWidth};}}),appendChild(){}}));
  const notes=Array.from({length:36},(_,i)=>({t:i*880,text:'笔记',content:[{type:'image',anchorRowId:`segment-${i*105}`,layout,displayWidth:200,width:800,height:450}]}));
  const feed={querySelectorAll:selector=>selector==='.seg:not(.sum)'?rows:[],
    insertBefore:(node,next)=>inserted.push({node,next}),querySelector:()=>rows[0],style:{}};
  const context=vm.createContext({$:id=>id==='feed'?feed:id==='allNotesPop'?{hidden:true}:{style:{}},view:{notes},
    clearImageDropPreview(){},resetImageAsideFlow(){},createNoteDom:t=>({t}),
    createTranscriptNoteImage:()=>({style:{},dataset:{}}),
    resolveImageAsideWidth:(width,preferred)=>width<112?0:preferred,
    resolveTranscriptImageLayout:(node,width)=>node.displayWidth>width*.7?{...node,layout:'inline'}:node,
    applyImageAsideFlow:(...args)=>asides.push(args),createTranscriptImageDivider(){}});
  vm.runInContext(html.match(/async function renderTimelineNotes\([^]*?\n\}/)[0],context);
  context.renderTimelineNotes();return {reads,inserted,asides,rows};
}
test('loading a long document with anchored inline images never forces paragraph layout',()=>{
  const result=render();assert.equal(result.reads,0);
  assert.equal(result.inserted.length,72);
  assert.equal(result.inserted[1].next,result.rows[0].nextSibling);
  assert.equal(result.rows[4041].dataset.rowId,'segment-4041');
});
test('aside images measure their anchor once and preserve narrow-column fallback',()=>{
  const wide=render('aside-left');assert.equal(wide.reads,36);assert.equal(wide.asides.length,36);
  assert.equal(wide.asides[0][1],200);assert.equal(wide.asides[0][2],112.5);
  const narrow=render('aside-right',100);assert.equal(narrow.reads,36);
  assert.equal(narrow.asides.length,0);assert.equal(narrow.inserted.length,72);
});
