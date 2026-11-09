const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');
const start = html.indexOf('(function(){', html.indexOf('/* ============ 侧栏拖拽入组'));
const source = html.slice(start, html.indexOf('\n})();', start) + 6);
function setup(batch=false){
  const events = {}, classes = new Set();
  let captured = null, leaves = 0, saves = 0;
  const scrollMoves = [], frames = [];
  let hits=0;
  const item = {dataset:{id:'one'}, classList:{add(){},remove(){}}, onmouseleave(){leaves++;}};
  const list = {addEventListener(type, fn){events[type]=fn;}, querySelectorAll(){return [item];},
    getBoundingClientRect(){return {top:20,bottom:220,left:0,right:200,height:200};},
    setPointerCapture(id){captured=id;}, hasPointerCapture(id){return captured===id;}, releasePointerCapture(){captured=null;}};
  const ctx = { $:id=>id==='histlist'?list:{classList:{remove(){}}},
    window:{addEventListener(type,fn){events[type]=fn;}},
    document:{body:{classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}},elementFromPoint:()=>{hits++;return null;}},
    state:'idle',sidebarDragging:false,sbJustDragged:false,selected:new Set(),lastHistRaw:[],
    requestAnimationFrame:fn=>frames.push(fn),
    scrollFrameUpdate:fn=>fn,
    sidebarDndKit:{
      DragDropManager:class {monitor={addEventListener(type,fn){events[type]=fn;}};actions={start:({coordinates})=>scrollMoves.push(coordinates),move:({to})=>scrollMoves.push(to),stop:()=>scrollMoves.push('stop')};},
      Draggable:class {},AutoScroller:{configure:options=>options},
    },
    createSidebarDragGhost:()=>({style:{},remove(){}}),moveSidebarDragGhost(){},
    esc:x=>x,fmt:x=>x,setTimeout:()=>1,clearTimeout(){},renderSelState(){},refreshHistory(){},
    api:async()=>{saves++;return {ok:true};},toast(){}};
  if(batch)vm.runInNewContext(html.match(/function scrollFrameUpdate\(update\)\{[^]*?\n\}/)[0],ctx);
  vm.runInNewContext(source,ctx);
  const point={button:0,pointerId:7,clientX:10,clientY:10,target:{closest:s=>s==='.hitem'?item:null}};
  return {events,point,ctx,classes,scrollMoves,frames,get hits(){return hits;},get captured(){return captured;},get leaves(){return leaves;},get saves(){return saves;}};
}
test('capture begins only after drag threshold and clears existing hover',()=>{
  const s=setup();s.events.pointerdown(s.point);
  assert.equal(s.captured,null);
  s.events.pointermove({...s.point,clientX:12});assert.equal(s.captured,null);
  s.events.pointermove({...s.point,clientX:20});
  assert.equal(s.captured,7);assert.equal(s.leaves,1);
  s.events.pointerup(s.point);assert.equal(s.captured,null);assert.equal(s.ctx.sidebarDragging,false);
});
test('cancel releases drag state without saving a drop',()=>{
  const s=setup();s.events.pointerdown(s.point);s.events.pointermove({...s.point,clientX:20});
  assert.equal(typeof s.events.pointercancel,'function');s.events.pointercancel(s.point);
  assert.equal(s.captured,null);assert.equal(s.classes.has('dragging'),false);assert.equal(s.saves,0);
});

test('sidebar forwards vertical overshoot to dnd-kit and stops on cancellation',()=>{
  const s=setup();
  s.events.pointerdown(s.point);
  s.events.pointermove({...s.point,clientY:245});
  s.events.dragstart();
  s.events.pointermove({...s.point,clientY:-40});
  s.events.pointercancel(s.point);
  assert.deepEqual(JSON.parse(JSON.stringify(s.scrollMoves)), [
    {x:10,y:10}, {x:10,y:219}, {x:10,y:21}, 'stop',
  ]);
});

test('pointer movement and scroll share a frame and use the latest pointer position',()=>{
  const s=setup(true);
  s.events.pointerdown(s.point);
  s.events.pointermove({...s.point,clientY:245});
  s.events.dragstart();
  s.events.pointermove({...s.point,clientY:140});
  s.events.pointermove({...s.point,clientY:150});
  s.events.scroll();
  assert.equal(s.frames.length,1);
  assert.equal(s.hits,0);
  s.frames.shift()();
  assert.equal(s.hits,1);
  assert.equal(s.scrollMoves.at(-1).y,150);
});
