const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const source = html.slice(html.indexOf('const temporaryPopupSelector'), html.indexOf('/* ---- 悬浮弹层统一模态:'));
function element(parent=null, overflowY='visible', zIndex='0') {
  return {parentElement:parent,nodeType:1,attrs:{},style:{overflowY,overflowX:'visible',zIndex},
    contains(other) { for(let el=other;el;el=el.parentElement)if(el===this)return true;return false; },
    getClientRects(){return [1];},closest(){return null;},
    setAttribute(key,value){this.attrs[key]=value;},removeAttribute(key){delete this.attrs[key];}};
}
function harness() {
  const background=element(null,'auto');
  const panel=element(null,'auto','60');
  const submenu=element(null,'visible','70');
  const list=element(panel,'auto');
  const state={popups:[],elements:[background,panel,submenu,list],scrollContainers:[background,panel,list]};
  const queries=[],styleReads=[];
  const listeners={};
  const document={querySelectorAll(selector){
    queries.push(selector);
    if(selector==='body *')return state.elements;
    if(selector.startsWith('.feedwrap,'))return state.scrollContainers;
    if(selector.startsWith('[data-'))return state.elements.filter(el=>selector.slice(1,-1) in el.attrs);
    return state.popups;
  },addEventListener(type,handler,options){listeners[type]={handler,options};}};
  const context=vm.createContext({document,getComputedStyle:el=>{styleReads.push(el);return el.style;},MutationObserver:class{observe(){}}});
  vm.runInContext(source,context);
  const send=(target,type='wheel',key)=>{
    const event={target,type,key,prevented:false,stopped:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
    listeners[type].handler(event);return event;
  };
  return {state,background,panel,submenu,list,context,send,queries,styleReads};
}
test('background wheel, touch and navigation keys stay blocked until the popup closes',()=>{
  const h=harness();h.state.popups=[h.panel];
  for(const [type,key] of [['wheel'],['touchmove'],['keydown','PageDown']])assert.equal(h.send(h.background,type,key).prevented,true);
  assert.equal(h.send(h.background,'keydown','Escape').prevented,false);
  h.state.popups=[];assert.equal(h.send(h.background).prevented,false);
});
test('only the top popup can scroll; nested picker locks its parent settings panel',()=>{
  const h=harness();h.state.popups=[h.panel];
  assert.equal(h.send(h.list).prevented,false);
  h.state.popups.push(h.submenu);
  assert.equal(h.send(h.list).prevented,true);
  assert.equal(h.send(h.submenu).prevented,true);
  const nested=element(h.panel,'auto','0');h.state.popups=[h.panel,nested];
  assert.equal(vm.runInContext('activeTemporaryPopup()',h.context),nested);
});
test('scroll locks restore without replacing existing overflow styles or scroll positions',()=>{
  const h=harness();h.background.scrollTop=123;h.state.popups=[h.panel];
  vm.runInContext('syncTemporaryPopupScroll()',h.context);
  assert.equal('data-popup-scroll-locked' in h.background.attrs,true);
  assert.equal('data-popup-scroll-locked' in h.list.attrs,false);
  assert.equal('data-popup-scroll-active' in h.panel.attrs,true);
  h.state.popups=[];vm.runInContext('syncTemporaryPopupScroll()',h.context);
  assert.deepEqual(h.background.attrs,{});assert.deepEqual(h.panel.attrs,{});
  assert.equal(h.background.style.overflowY,'auto');assert.equal(h.background.scrollTop,123);
});
test('picker is not dismissed by settings scroll and playback follow pauses during popups',()=>{
  assert.doesNotMatch(html,/addEventListener\('scroll',\s*\(\)=>\{ pickClose\(\);/);
  assert.match(html,/function followTo\(hit\)\{\s*if\(activeTemporaryPopup\(\)\) return;/);
  assert.match(html,/\[data-popup-scroll-active\] \*\{overscroll-behavior:contain;/);
});
test('opening a popup does not enumerate body descendants or read background styles',()=>{
  const h=harness();h.state.popups=[h.panel];
  const unrelated=Array.from({length:5000},()=>element());
  h.state.elements.push(...unrelated);
  h.queries.length=0;h.styleReads.length=0;
  vm.runInContext('syncTemporaryPopupScroll()',h.context);
  assert.equal(h.queries.includes('body *'),false);
  assert.equal(h.styleReads.length,0);
  assert.ok(unrelated.every(el=>!('data-popup-scroll-locked' in el.attrs)));
  assert.equal('data-popup-scroll-locked' in h.background.attrs,true);
});
test('nested popup locks the parent scroll area and restores it when dismissed',()=>{
  const h=harness();h.state.popups=[h.panel,h.submenu];
  vm.runInContext('syncTemporaryPopupScroll()',h.context);
  assert.equal('data-popup-scroll-locked' in h.panel.attrs,true);
  assert.equal('data-popup-scroll-locked' in h.list.attrs,true);
  assert.equal('data-popup-scroll-active' in h.submenu.attrs,true);
  h.state.popups=[h.panel];vm.runInContext('syncTemporaryPopupScroll()',h.context);
  assert.equal('data-popup-scroll-locked' in h.panel.attrs,false);
  assert.equal('data-popup-scroll-locked' in h.list.attrs,false);
  assert.equal('data-popup-scroll-active' in h.submenu.attrs,false);
  assert.equal('data-popup-scroll-active' in h.panel.attrs,true);
});
test('repeated open/close retains inline overflow and scroll position',()=>{
  const h=harness();h.background.scrollTop=321;h.panel.scrollTop=87;
  for(let i=0;i<10;i++){
    h.state.popups=[h.panel];vm.runInContext('syncTemporaryPopupScroll()',h.context);
    h.state.popups=[];vm.runInContext('syncTemporaryPopupScroll()',h.context);
  }
  assert.equal(h.background.scrollTop,321);assert.equal(h.panel.scrollTop,87);
  assert.equal(h.background.style.overflowY,'auto');assert.equal(h.panel.style.overflowY,'auto');
  assert.deepEqual(h.background.attrs,{});assert.deepEqual(h.panel.attrs,{});
});
test('explicit scroll targets cover current scrollable CSS containers and textareas',()=>{
  const h=harness();
  const targets=vm.runInContext('temporaryPopupScrollSelector',h.context).split(',');
  const css=html.split('<style>')[1].split('</style>')[0].replace(/\/\*[\s\S]*?\*\//g,'');
  for(const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)){
    if(!/overflow(?:-[xy])?\s*:\s*(?:auto|scroll)\b/.test(match[2]))continue;
    for(const selector of match[1].trim().split(',')){
      assert.ok(targets.includes(selector.trim().replace(/\.(viewing|expanded)$/,'')),selector.trim());
    }
  }
  assert.ok(targets.includes('textarea'));
});
