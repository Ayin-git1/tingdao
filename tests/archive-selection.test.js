const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');
function setup() {
  const start = html.indexOf('const archiveSelected = new Set();');
  assert.ok(start >= 0, 'archive selection should have independent state');
  const end = html.indexOf('function renderCollectionPanel()', start);
  const nodes = {};
  const context = vm.createContext({section:'archive', view:null, state:'idle', lastHistRaw:[{id:'a',archived:true},{id:'b',archived:true},{id:'pending',archived:true,pending:true},{id:'doc'}],
    sectionItems: (items)=>items.filter(it=>it.archived),
    $: id=>nodes[id] ||= {classList:{toggle(){}},hidden:false},
    renderCollectionPanel(){}, openDelModal(ids,options){context.deletion={ids,options};}
  });
  vm.runInContext(html.slice(start,end),context);
  return {context,nodes,run:code=>vm.runInContext(code,context)};
}
test('select all excludes pending and non-archived projects and toggles off',()=>{
  const {run,nodes}=setup();
  run('toggleArchiveAll()');
  assert.deepEqual(Array.from(run('[...archiveSelected]')),['a','b']);
  assert.equal(nodes.archiveSelectAll.textContent,'取消全选');
  run('toggleArchiveAll()');
  assert.equal(run('archiveSelected.size'),0);
});
test('refresh prunes restored or deleted projects and leaving page clears selection',()=>{
  const {run,context}=setup();
  run('toggleArchiveAll(); lastHistRaw = lastHistRaw.filter(it=>it.id !== "a"); syncArchiveSelection()');
  assert.deepEqual(Array.from(run('[...archiveSelected]')),['b']);
  context.section='favorites'; run('syncArchiveSelection()');
  assert.equal(run('archiveSelected.size'),0);
});
test('batch delete uses archive confirmation with only checked IDs',()=>{
  const {run,context,nodes}=setup();
  run('toggleArchiveSelection("b");');
  nodes.archiveDelete.onclick();
  assert.deepEqual(Array.from(context.deletion.ids),['b']);
  assert.equal(context.deletion.options.archiveDelete,true);
});
