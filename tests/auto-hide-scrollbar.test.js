const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const source=html.match(/function overlayScrollbarGeometry\(viewport,total,position\)\{[\s\S]*?\n\}/);
assert.ok(source);
const context=vm.createContext({});vm.runInContext(source[0],context);
const geometry=context.overlayScrollbarGeometry;
test('thumb tracks scroll position proportionally and reaches both ends',()=>{
  assert.equal(geometry(200,1000,0).offset,0);
  assert.equal(geometry(200,1000,400).offset,80);
  assert.equal(geometry(200,1000,800).offset,160);
  assert.equal(geometry(200,1000,800).size,40);
});
test('long documents retain a draggable minimum thumb and clamp rubber-band overscroll',()=>{
  assert.equal(geometry(200,100000,-50).size,24);
  assert.equal(geometry(200,100000,-50).offset,0);
  assert.equal(geometry(200,100000,100000).offset,176);
});
test('unscrollable and tiny containers produce finite bounded geometry',()=>{
  for(const [viewport,total] of [[200,200],[200,100],[10,1000]]){
    const g=geometry(viewport,total,0);
    assert.ok(g.size<=viewport);assert.ok(Number.isFinite(g.offset));
    assert.ok(g.travel>=0);assert.ok(g.range>=0);
  }
});
test('native gutters are disabled and overlay tracks never enter document flow',()=>{
  assert.match(html,/\*\{scrollbar-width:none;\}/);
  assert.match(html,/::-webkit-scrollbar\{width:0;height:0;\}/);
  assert.match(html,/\.td-scrollbar\{position:fixed;/);
  assert.doesNotMatch(html,/scrollbar-gutter:stable/);
});
function stackingHarness(){
  const normal={position:'static',zIndex:'auto',opacity:'1',isolation:'auto',transform:'none',translate:'none',rotate:'none',scale:'none',filter:'none',backdropFilter:'none',perspective:'none',willChange:'auto',contain:'none'};
  const body={parentElement:null,style:normal};
  const ctx=vm.createContext({document:{body},getComputedStyle:el=>el.style});
  for(const name of ['overlayScrollbarHost','overlayScrollbarOrigin']){
    const fn=html.match(new RegExp('function '+name+'\\([^)]*\\)\\{[\\s\\S]*?\\n\\}'));
    assert.ok(fn);vm.runInContext(fn[0],ctx);
  }
  const node=(parent,style={})=>({parentElement:parent,style:{...normal,...style}});
  return {body,node,host:ctx.overlayScrollbarHost,origin:ctx.overlayScrollbarOrigin};
}
test('scrollbar stays in its page stacking context so higher pages and dialogs cover it',()=>{
  const h=stackingHarness();
  const page=h.node(h.body,{position:'relative',zIndex:'2'});
  const wrap=h.node(page),scroller=h.node(wrap);
  assert.equal(h.host(scroller),page);
  assert.equal(h.origin(page).x,0);
});
test('translated sidebars provide a local fixed origin rather than double-applying their offset',()=>{
  const h=stackingHarness();
  const sidebar=h.node(h.body,{translate:'80px'});
  Object.assign(sidebar,{clientLeft:1,clientTop:1,scrollLeft:0,scrollTop:20,getBoundingClientRect:()=>({left:300,top:120})});
  assert.equal(h.host(h.node(sidebar)),sidebar);
  const origin=h.origin(sidebar);
  assert.equal(origin.x,301);assert.equal(origin.y,101);
});
test('a top-level scrolling panel shares its own layer instead of the global tooltip layer',()=>{
  const h=stackingHarness();
  assert.equal(h.host(h.node(h.body,{position:'fixed',zIndex:'51'})),h.body);
  assert.match(html,/--scrollbar-layer',style\.zIndex==='auto'\?'0':style\.zIndex/);
  assert.doesNotMatch(html,/\.td-scrollbar\{[^}]*--z-tip/);
});
test('home recent projects keep scrolling without showing the overlay scrollbar',()=>{
  assert.match(html,/bar\.track\.hidden=el\.classList\.contains\('no-overlay-scrollbar'\)\|\|/);
  assert.match(html,/\$\('feedwrap'\)\.classList\.toggle\('no-overlay-scrollbar', welcome\)/);
  assert.match(html,/\.feedwrap\{flex:1; overflow-y:auto;/);
});
