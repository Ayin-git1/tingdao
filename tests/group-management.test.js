const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const source = html.slice(html.indexOf('function reorderedGroupNames('), html.indexOf('async function setGroupColor('));
test('group order supports moving before and after a target', () => {
  const context = vm.createContext({});
  vm.runInContext(source, context);
  const names = ['A', 'B', 'C'];
  assert.deepEqual(Array.from(context.reorderedGroupNames(names, 'C', 'A', false)), ['C', 'A', 'B']);
  assert.deepEqual(Array.from(context.reorderedGroupNames(names, 'A', 'C', true)), ['B', 'C', 'A']);
  assert.equal(context.reorderedGroupNames(names, 'A', 'A', false), names);
  assert.equal(context.reorderedGroupNames(names, 'missing', 'A', false), names);
});
test('reorder saves metadata and refreshes only after successful persistence', async () => {
  for (const ok of [true, false]) {
    const original = {order:['A', 'B'], collapsed:['B'], colors:{A:'blue'}};
    let payload, refreshed = 0, rendered = 0, error;
    const context = vm.createContext({
      groupMeta:original, groupNamesWithCounts:()=>[{name:'A'}, {name:'B'}],
      api:async (url, data)=>{ assert.equal(url, '/api/groups'); payload = data; return {ok}; },
      refreshHistory:async()=>{refreshed++;}, renderGpop:()=>{rendered++;}, toast:message=>{error = message;},
    });
    vm.runInContext(source, context);
    await context.reorderGroups('B', 'A', false);
    assert.deepEqual(Array.from(payload.order), ['B', 'A']);
    assert.equal(payload.collapsed, original.collapsed);
    assert.equal(payload.colors, original.colors);
    assert.equal(refreshed, ok ? 1 : 0);
    assert.equal(rendered, ok ? 1 : 0);
    if(!ok){ assert.equal(context.groupMeta, original); assert.ok(error); }
  }
});
test('dragging the handle with pointer events commits the target order; cancellation does not', async () => {
  const dragSource = html.slice(html.indexOf('function bindGroupReorder('), html.indexOf('function reorderedGroupNames('));
  for(const inline of [false, true]) for(const cancelled of [false, true]){
    let captured = false, saved;
    const handle = {setPointerCapture(){captured = true;}, hasPointerCapture(){return captured;}, releasePointerCapture(){captured = false;}};
    const row = {querySelector:()=>({textContent:'2'}), dataset:{groupName:'A'}, style:{}, classList:{add(){},remove(){}}, getBoundingClientRect:()=>({top:0,bottom:35,left:0,width:200})};
    const target = {style:{}, dataset:{groupName:'B'}, getBoundingClientRect:()=>({top:40,bottom:80}), classList:{add(){},remove(){}}};
    const box = {classList:{add(){},remove(){}}, querySelectorAll:selector=>selector === '.drag-over' ? [target] : [row, target]};
    let indicator;
    const context = vm.createContext({sidebarGroupSorting:true, esc:value=>value, createSidebarDragGhost:()=>({style:{},remove(){}}), moveSidebarDragGhost(){}, document:{createElement:()=>{indicator = {style:{},remove(){}}; return indicator;}, body:{appendChild(){}}}, reorderGroups:async(...args)=>{saved = args;}});
    vm.runInContext(dragSource, context);
    context.bindGroupReorder(handle, row, box, 'A', inline);
    const event = {button:0, pointerId:1, clientX:10, clientY:10, preventDefault(){}, stopPropagation(){}};
    handle.onpointerdown(event);
    assert.equal(captured, false);
    handle.onpointermove({...event, clientY:75});
    assert.ok(captured);
    assert.equal(row.style.transform, inline ? '' : 'translate(0px, 65px)');
    if(inline){ assert.equal(indicator.style.width, '176px'); assert.equal(indicator.style.top, '41px'); }
    assert.equal(target.style.transform, 'translateY(-40px)');
    await handle.onpointerup({...event, type:cancelled ? 'pointercancel' : 'pointerup'});
    assert.equal(captured, false);
    assert.equal(row.style.transform, '');
    assert.equal(target.style.transform, '');
    assert.equal(handle.onpointermove, null);
    if(cancelled) assert.equal(saved, undefined);
    else assert.deepEqual(saved, ['A','B',true]);
  }
});
