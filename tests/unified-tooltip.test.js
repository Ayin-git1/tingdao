const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const source=html.slice(html.indexOf('/* ---- 悬浮提示气泡'),html.indexOf('/* ---- 说话人列表'));

function element(attrs={},rect={left:100,right:140,top:100,bottom:130,width:40,height:30}){
  const data={},classes=new Set();
  return {
    attrs:{...attrs},dataset:data,style:{},textContent:attrs.text||'',isConnected:true,offsetWidth:60,offsetHeight:20,parent:null,
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),has:c=>classes.has(c),contains:c=>classes.has(c)},
    getAttribute(k){return k in this.attrs?this.attrs[k]:null;},
    hasAttribute(k){return k in this.attrs;},
    setAttribute(k,v){this.attrs[k]=String(v);},
    removeAttribute(k){delete this.attrs[k];},
    getBoundingClientRect:()=>rect,
    matches(){return this.attrs.tag==='button';},
    contains(other){for(let n=other;n;n=n.parent)if(n===this)return true;return false;},
    closest(){for(let n=this;n;n=n.parent)if('title' in n.attrs||'tip' in n.dataset)return n;return null;}
  };
}
function setup(){
  const tip=element(),handlers={},timers=new Map();let nextTimer=1,observerCallback;
  const docListeners=(type,fn)=>{(handlers[type]=handlers[type]||[]).push(fn);};
  const document={addEventListener:docListeners,documentElement:{},contains:()=>true};
  const ctx={
    $:()=>tip,document,innerWidth:800,innerHeight:600,
    addEventListener:docListeners,
    setTimeout(fn,ms){timers.set(nextTimer,{fn,ms});return nextTimer++;},
    clearTimeout(id){timers.delete(id);},
    MutationObserver:class{constructor(cb){observerCallback=cb;}observe(){}}
  };
  vm.createContext(ctx);vm.runInContext(source,ctx);
  const fire=(type,event={})=>(handlers[type]||[]).forEach(fn=>fn(event));
  const over=target=>fire('mouseover',{target,buttons:0});
  const flush=()=>{const list=[...timers.values()];timers.clear();list.forEach(t=>t.fn());return list;};
  const mutate=target=>observerCallback([{target}]);
  return {tip,fire,over,flush,mutate,timers};
}

test('title hover moves into the built-in bubble so the native tooltip never fires',()=>{
  const t=setup(),b=element({title:'归档',tag:'button'});
  t.over(b);
  assert.equal(b.hasAttribute('title'),false);
  assert.equal(b.dataset.tip,'归档');
  assert.equal(t.tip.classList.has('show'),false,'waits for the delay');
  t.flush();
  assert.equal(t.tip.textContent,'归档');
  assert.equal(t.tip.classList.has('show'),true);
});

test('title and data-tip share one delay',()=>{
  const t=setup(),a=element({title:'甲'}),b=element();b.dataset.tip='乙';
  t.over(a);const [first]=[...t.timers.values()];
  t.over(b);const [second]=[...t.timers.values()];
  assert.ok(first.ms>0);
  assert.equal(first.ms,second.ms);
  assert.equal(t.timers.size,1,'moving on cancels the previous timer');
});

test('leaving before the delay shows nothing',()=>{
  const t=setup(),b=element({title:'甲'});
  t.over(b);t.over(element());t.flush();
  assert.equal(t.tip.classList.has('show'),false);
});

test('moving inside the same control does not restart the delay',()=>{
  const t=setup(),b=element({title:'甲'}),icon=element();icon.parent=b;
  t.over(b);t.over(icon);
  assert.equal(t.timers.size,1);
  t.flush();assert.equal(t.tip.classList.has('show'),true);
  t.over(icon);assert.equal(t.tip.classList.has('show'),true);
});

test('icon-only buttons keep an accessible name, labelled ones keep theirs, and it follows title updates',()=>{
  const t=setup(),icon=element({title:'暂停',tag:'button'}),named=element({title:'甲','aria-label':'原名',tag:'button'}),text=element({title:'甲',tag:'button',text:'替换'});
  t.over(icon);t.over(named);t.over(text);
  assert.equal(icon.getAttribute('aria-label'),'暂停');
  assert.equal(named.getAttribute('aria-label'),'原名');
  assert.equal(text.hasAttribute('aria-label'),false);
  icon.setAttribute('title','继续');t.mutate(icon);
  assert.equal(icon.getAttribute('aria-label'),'继续');
});

test('a title written later is taken over and updates the open bubble',()=>{
  const t=setup(),b=element({title:'新建',tag:'button'});
  t.over(b);t.flush();
  b.setAttribute('title','停止录音');t.mutate(b);
  assert.equal(b.hasAttribute('title'),false);
  assert.equal(t.tip.textContent,'停止录音');
  assert.equal(t.tip.classList.has('show'),true);
});

test('the empty title clears the tip, and our own removal does not',()=>{
  const t=setup(),b=element({title:'请按 分:秒 输入'});
  t.over(b);t.flush();
  t.mutate(b);
  assert.equal(b.dataset.tip,'请按 分:秒 输入','removal record from adoption is ignored');
  b.setAttribute('title','');t.mutate(b);
  assert.equal('tip' in b.dataset,false);
  assert.equal(t.tip.classList.has('show'),false);
});

test('pressing dismisses and the tip stays away until the pointer leaves',()=>{
  const t=setup(),b=element({title:'甲'}),icon=element();icon.parent=b;
  t.over(b);t.flush();
  t.fire('mousedown',{target:b});
  assert.equal(t.tip.classList.has('show'),false);
  t.over(icon);
  assert.equal(t.timers.size,0);
  t.over(element());t.over(b);
  assert.equal(t.timers.size,1);
});

test('pending tips are cancelled by press, key and window blur; a held button starts none',()=>{
  for(const type of ['mousedown','keydown','blur']){
    const t=setup();t.over(element({title:'甲'}));t.fire(type,{target:{}});
    assert.equal(t.timers.size,0,type);
  }
  const t=setup();t.fire('mouseover',{target:element({title:'甲'}),buttons:1});
  assert.equal(t.timers.size,0);
});

test('only a scroll that moves the anchor dismisses it, so playback follow does not kill the tip',()=>{
  const t=setup(),b=element({title:'甲'}),feed=element(),box=element();b.parent=box;
  t.over(b);
  t.fire('scroll',{target:feed});
  assert.equal(t.timers.size,1);
  t.fire('scroll',{target:box});
  assert.equal(t.timers.size,0);
});

test('a control removed during the delay shows nothing',()=>{
  const t=setup(),b=element({title:'甲'});
  t.over(b);b.isConnected=false;t.flush();
  assert.equal(t.tip.classList.has('show'),false);
});

test('the bubble stays in the viewport: flips above at the bottom, clamps at the sides',()=>{
  const t=setup();
  const low=element({title:'播放'},{left:100,right:140,top:570,bottom:595,width:40,height:25});
  t.over(low);t.flush();
  assert.ok(parseFloat(t.tip.style.top)<570,`above the control, got ${t.tip.style.top}`);
  const edge=element({title:'关闭'},{left:770,right:798,top:10,bottom:30,width:28,height:20});
  t.over(edge);t.flush();
  assert.equal(parseFloat(t.tip.style.left),800-8-30);
  assert.ok(parseFloat(t.tip.style.top)>30);
});

test('nothing in the app depends on reading title back from the DOM',()=>{
  assert.doesNotMatch(html,/op\.title\s*===/);
  assert.doesNotMatch(html,/button\[title=/);
});

test('long tips wrap instead of running off the screen',()=>{
  const rule=html.match(/#tip\{[^}]*\}/)[0];
  assert.match(rule,/max-width:/);
  assert.doesNotMatch(rule,/white-space:nowrap/);
});
