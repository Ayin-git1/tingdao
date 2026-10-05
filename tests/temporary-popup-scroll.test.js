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
  const state={popups:[],elements:[background,panel,submenu,list]};
  const listeners={};
  const document={querySelectorAll(selector){
    if(selector==='body *')return state.elements;
    if(selector.startsWith('[data-'))return state.elements.filter(el=>selector.slice(1,-1) in el.attrs);
    return state.popups;
  },addEventListener(type,handler,options){listeners[type]={handler,options};}};
  const context=vm.createContext({document,getComputedStyle:el=>el.style,MutationObserver:class{observe(){}}});
  vm.runInContext(source,context);
  const send=(target,type='wheel',key)=>{
    const event={target,type,key,prevented:false,stopped:false,preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
    listeners[type].handler(event);return event;
  };
  return {state,background,panel,submenu,list,context,send};
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
