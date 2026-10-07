const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const source=html.slice(html.indexOf('let pausePending ='),html.indexOf('/* ---- 临时弹层滚动隔离'));
function setup(state='recording'){
  const classes=new Set(),attrs={};
  const button={classList:{toggle(name,on){on?classes.add(name):classes.delete(name);}},setAttribute(name,value){attrs[name]=value;}};
  let iconWrites=0,icon='';
  Object.defineProperty(button,'innerHTML',{get(){return icon;},set(value){icon=value;iconWrites++;}});
  let resolve,reject,requests=0;
  const pending=new Promise((yes,no)=>{resolve=yes;reject=no;});
  const ctx={state,$:()=>button,api:()=>{requests++;return pending;},fetchStatus:async()=>({state:state==='paused'?'recording':'paused'}),applyStatus(d){ctx.state=d.state;ctx.syncPauseButton();},toast(){}};
  vm.createContext(ctx);vm.runInContext(source,ctx);
  return {ctx,button,classes,attrs,resolve,reject,get requests(){return requests;},get iconWrites(){return iconWrites;}};
}
test('pause remains visible and busy through polling; duplicate clicks are blocked',async()=>{
  const t=setup();const first=t.button.onclick();
  assert.equal(t.button.disabled,true);assert.match(t.button.innerHTML,/pause-spinner/);
  t.ctx.syncPauseButton();await t.button.onclick();assert.equal(t.requests,1);
  assert.equal(t.attrs['aria-busy'],'true');t.resolve({ok:true});await first;
  assert.equal(t.button.disabled,false);assert.equal(t.classes.has('paused'),true);
  assert.doesNotMatch(t.button.innerHTML,/pause-spinner/);assert.equal(t.button.title,'继续录音');
});
test('resume clears paused indication after completion',async()=>{
  const t=setup('paused');const first=t.button.onclick();t.resolve({ok:true});await first;
  assert.equal(t.classes.has('paused'),false);assert.equal(t.button.title,'暂停录音');
});
test('network and API failures restore the button',async()=>{
  for(const fail of ['network','api']){
    const t=setup();const first=t.button.onclick();
    if(fail==='network')t.reject(new Error('offline'));else t.resolve({error:'failed'});
    await first;assert.equal(t.button.disabled,false);assert.equal(t.attrs['aria-busy'],'false');assert.doesNotMatch(t.button.innerHTML,/pause-spinner/);
  }
});

test('status updates preserve the spinning icon instead of restarting its animation',async()=>{
  const t=setup();const first=t.button.onclick();
  const writes=t.iconWrites;
  for(let i=0;i<10;i++)t.ctx.syncPauseButton();
  t.ctx.state='paused';t.ctx.syncPauseButton();
  assert.equal(t.iconWrites,writes);
  t.resolve({ok:true});await first;
  assert.equal(t.iconWrites,writes+1);
  t.ctx.syncPauseButton();assert.equal(t.iconWrites,writes+1);
});
