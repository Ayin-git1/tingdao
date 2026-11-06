const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
test('review disables background content while leaving settings and scrims interactive, then restores it',()=>{
  const classes=()=>({toggle(){},contains(){return false;}});
  const main={inert:false},sidebar={inert:false},feed={inert:false},collection={inert:true},audio={inert:false},level={inert:false};
  const nodes={'.main':main,'.sidebar':sidebar,'.feedzone':feed,'#collectionPanel':collection,'#audiobar':audio,'#lvlbar':level};
  const elements={};const $=id=>elements[id]??=( {classList:classes(),setAttribute(){},focus(){}} );
  const ctx=vm.createContext({gr:{open:false,busy:false,epoch:0},state:'idle',document:{querySelectorAll:selector=>selector.split(',').map(s=>{assert.ok(nodes[s],s);return nodes[s];}),body:{classList:classes()}},$,toast(){},grSlide(){},grSoundSync(){},syncRailVisibility(){},closePops(){},closeAllNotes(){},openDrawer(){},reviewSetOpen(){},grRender(){},grReload(){}});
  vm.runInContext(html.slice(html.indexOf('function grSetOpen(open){'),html.indexOf('function grSlide(open){')),ctx);
  ctx.grSetOpen(true);
  assert.equal(main.inert,false,'settings and scrims inherit main inert');
  for(const el of [sidebar,feed,collection,audio,level])assert.equal(el.inert,true);
  ctx.grSetOpen(false);
  for(const el of [sidebar,feed,audio,level])assert.equal(el.inert,false);
  assert.equal(collection.inert,true,'preserve a pre-existing disabled state');
});
function shortcutHarness(popup){
  let handler;const calls=[];
  const ctx=vm.createContext({gr:{open:true,tab:'focus'},activeTemporaryPopup:()=>popup,document:{addEventListener:(type,fn)=>handler=fn},$:()=>({focus(){}}),grTab:()=>calls.push('tab'),grSetOpen:()=>calls.push('close'),grTurnPage:()=>calls.push('page'),grPeel:()=>calls.push('peel'),grUndo:()=>calls.push('undo'),grChoose:()=>calls.push('grade'),REVIEW_GRADES:[['again'],['hard'],['good'],['easy']]});
  const start=html.indexOf("document.addEventListener('keydown',e=>{\n  if(!gr.open");
  vm.runInContext(html.slice(start,html.indexOf("document.addEventListener('visibilitychange'",start)),ctx);
  return {calls,send:key=>handler({key,target:{closest:()=>false},preventDefault(){},stopImmediatePropagation(){}}),ctx};
}
test('a popup owns Escape, space, grades and search before global review shortcuts',()=>{
  const h=shortcutHarness({});for(const key of ['Escape',' ','1','z'])h.send(key);
  h.ctx.gr.tab='knowledge';for(const key of ['q','e'])h.send(key);
  assert.deepEqual(h.calls,[]);
});
test('review shortcuts resume when the popup is closed',()=>{
  const h=shortcutHarness(null);for(const key of [' ','1','z','Escape'])h.send(key);
  assert.deepEqual(h.calls,['peel','grade','undo','close']);
});
