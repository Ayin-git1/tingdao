const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');
const start = html.indexOf('(function(){', html.indexOf('/* ============ 侧栏拖拽入组'));
const source = html.slice(start, html.indexOf('\n})();', start) + 6);
function setup(){
  const events = {}, classes = new Set();
  let captured = null, leaves = 0, saves = 0;
  const item = {dataset:{id:'one'}, classList:{add(){},remove(){}}, onmouseleave(){leaves++;}};
  const list = {addEventListener(type, fn){events[type]=fn;}, querySelectorAll(){return [item];},
    setPointerCapture(id){captured=id;}, hasPointerCapture(id){return captured===id;}, releasePointerCapture(){captured=null;}};
  const ctx = { $:id=>id==='histlist'?list:{classList:{remove(){}}},
    window:{addEventListener(type,fn){events[type]=fn;}},
    document:{body:{classList:{add:c=>classes.add(c),remove:c=>classes.delete(c)}},elementFromPoint:()=>null},
    state:'idle',sidebarDragging:false,sbJustDragged:false,selected:new Set(),lastHistRaw:[],
    createSidebarAutoScroller:()=>({update(){},stop(){}}),requestAnimationFrame(){},cancelAnimationFrame(){},
    createSidebarDragGhost:()=>({style:{},remove(){}}),moveSidebarDragGhost(){},
    esc:x=>x,fmt:x=>x,setTimeout:()=>1,clearTimeout(){},renderSelState(){},refreshHistory(){},
    api:async()=>{saves++;return {ok:true};},toast(){}};
  vm.runInNewContext(source,ctx);
  const point={button:0,pointerId:7,clientX:10,clientY:10,target:{closest:s=>s==='.hitem'?item:null}};
  return {events,point,ctx,classes,get captured(){return captured;},get leaves(){return leaves;},get saves(){return saves;}};
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
