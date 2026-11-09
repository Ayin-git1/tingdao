const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
function source(name){const start=html.indexOf(`function ${name}(`);assert.notEqual(start,-1,name);return html.slice(start,html.indexOf('\n}',start)+2);}
function load(extra={}){
  const ctx=vm.createContext({Math,Number,...extra});
  vm.runInContext(html.match(/const IMAGE_ASIDE_MIN_TEXT=[^\n]*/)[0].replace('const ','var '),ctx);
  vm.runInContext(source('fitTranscriptImageAside'),ctx);
  return ctx;
}

test('aside width keeps the saved size while the column has room and shrinks when it does not',()=>{
  const ctx=load();
  assert.equal(ctx.fitTranscriptImageAside(616,260),260);
  // 栏变窄：图片收窄，给文字留出 160px
  assert.equal(ctx.fitTranscriptImageAside(400,260),224);
  // 连 96px 的图都放不下：返回 0，改为独占一行
  assert.equal(ctx.fitTranscriptImageAside(260,260),0);
  assert.equal(ctx.fitTranscriptImageAside(0,260),0);
});

function makeAnchor(contentWidth,saved){
  const classes=new Set(['image-aside-row']), props={};
  const figure={dataset:{noteDisplayWidth:String(saved),side:'right'},style:{},querySelector:()=>({width:800,height:450})};
  const divider={style:{}};
  const anchor={classList:{toggle:(c,on)=>on?classes.add(c):classes.delete(c)},
    style:{setProperty:(k,v)=>props[k]=v,removeProperty:k=>delete props[k]},
    querySelector:s=>s==='.transcript-note-image'?figure:s==='.tx'?{getBoundingClientRect:()=>({width:contentWidth})}:divider};
  return {anchor,figure,divider,classes,props};
}
function refresh(contentWidth,saved){
  const item=makeAnchor(contentWidth,saved), flows=[];
  const ctx=load({keepTranscriptReadingPosition:layout=>layout(),resetImageAsideFlow(){},applyImageAsideFlow:(...a)=>flows.push(a),
    $:()=>({querySelectorAll:()=>[item.anchor]})});
  vm.runInContext(source('refreshTranscriptImageAsideFlow')+source('layoutTranscriptImageAsideFlow'),ctx);
  ctx.refreshTranscriptImageAsideFlow();
  return {...item,flows};
}

test('refresh reflows aside images at the current column width without rewriting the saved width',()=>{
  const wide=refresh(616,260);
  assert.equal(wide.figure.style.width,'260px');
  assert.equal(wide.flows[0][1],260);
  assert.equal(wide.classes.has('image-aside-collapsed'),false);
  const narrow=refresh(400,260);
  assert.equal(narrow.figure.style.width,'224px');
  assert.equal(narrow.flows[0][1],224);
  assert.equal(narrow.props['--image-aside-width'],'224px');
  assert.equal(narrow.figure.dataset.noteDisplayWidth,'260');
});

test('a column too narrow to wrap text moves the image below its paragraph instead of overlapping',()=>{
  const r=refresh(240,260);
  assert.equal(r.classes.has('image-aside-collapsed'),true);
  assert.equal(r.flows.length,0);
  assert.equal(r.figure.style.width,'240px');
  assert.equal(r.figure.dataset.noteDisplayWidth,'260');
  assert.match(html,/\.image-aside-collapsed>\.transcript-note-image\{position:relative;/);
});

function loadKeeper({drift,hit=true}){
  const rowRect={top:100},wrapRect={top:0,left:0,width:800};
  const row={isConnected:true,getBoundingClientRect:()=>rowRect};
  const wrap={scrollTop:500,getBoundingClientRect:()=>wrapRect};
  const ctx=vm.createContext({Math,$:()=>wrap,document:{elementFromPoint:()=>hit?{closest:()=>row}:null}});
  vm.runInContext(source('transcriptReadingAnchor')+source('keepTranscriptReadingPosition')+source('restoreTranscriptReadingPosition'),ctx);
  return {ctx,wrap,move:()=>{rowRect.top+=drift;}};
}
test('reflow puts the row at the top of the viewport back where it was, however layout moved it',()=>{
  // 跟滚动方向无关：段落被带上去或带下去都要补回
  for(const drift of [84,-84]){
    const {ctx,wrap,move}=loadKeeper({drift});
    ctx.keepTranscriptReadingPosition(move);
    assert.equal(wrap.scrollTop,500+drift);
  }
});
test('reflow leaves scrolling alone when nothing moved or no row is under the viewport top',()=>{
  const still=loadKeeper({drift:0});still.ctx.keepTranscriptReadingPosition(still.move);
  assert.equal(still.wrap.scrollTop,500);
  const empty=loadKeeper({drift:84,hit:false});let ran=false;
  empty.ctx.keepTranscriptReadingPosition(()=>{ran=true;});
  assert.equal(ran,true);assert.equal(empty.wrap.scrollTop,500);
});
test('rebuilding notes after a save keeps the reading position, but opening a document does not',()=>{
  const render=source('renderTimelineNotes');
  assert.match(render,/const readingAnchor=isCurrent\?null:transcriptReadingAnchor\(\);/);
  assert.ok(render.indexOf('restoreTranscriptReadingPosition(readingAnchor)')>render.indexOf('resetImageAsideFlow()'));
});
