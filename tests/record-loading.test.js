const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const source=html.slice(html.indexOf('let recordLoadingBusy='),html.indexOf('async function waitForFinishThenLoad'));
function setup(state='idle'){
  const elements={};
  const element=id=>elements[id] ||= {hidden:true,inert:false,disabled:false,value:'',style:{},classList:{add(){},remove(){}},focus(){},addEventListener(){}};
  const sibling={inert:false},alreadyInert={inert:true};
  let tick,requests=0,resolve,reject;
  const pending=new Promise((yes,no)=>{resolve=yes;reject=no;});
  const ctx={state,view:null,transcriptViewGeneration:0,selected:new Set(),mode:'mic',langSel:'zh',recordingImageStopping:false,recordingImageUploads:[],sessionName:'',
    document:{body:{children:[sibling,alreadyInert,element('recordLoading')]},activeElement:null},window:{addEventListener(){}},
    $:element,setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>{tick=null;},Math,
    api:()=>{requests++;return pending;},defaultName:()=> 'test',renderSelState(){},toast(){},updateRefineUI(){},editBarOff(){},resetPlaybackSegments(){},updateChrome(){},
    settleLiveRow(){},refreshHistory(){},waitForFinishThenLoad:async()=>{},pumpTimer:null};
  vm.createContext(ctx);vm.runInContext(source,ctx);
  return {ctx,element,sibling,alreadyInert,resolve,reject,get requests(){return requests;},get tick(){return tick;}};
}
test('loading rotates without immediate repeats and restores existing inert state',()=>{
  const t=setup();
  assert.equal(t.ctx.showRecordLoading('start'),true);
  assert.equal(t.element('recordLoading').hidden,false);assert.equal(t.sibling.inert,true);
  for(let i=0;i<20;i++){const previous=t.element('recordLoadingText').textContent;t.tick();assert.notEqual(t.element('recordLoadingText').textContent,previous);}
  assert.equal(t.ctx.showRecordLoading('stop'),false);
  t.ctx.hideRecordLoading();assert.equal(t.tick,null);assert.equal(t.sibling.inert,false);assert.equal(t.alreadyInert.inert,true);
});
test('rapid start clicks make one request; rejection clears overlay',async()=>{
  const t=setup();const first=t.element('fab').onclick();await t.element('fab').onclick();
  assert.equal(t.requests,1);assert.equal(t.element('recordLoading').hidden,false);
  t.reject(new Error('offline'));await first;
  assert.equal(t.element('recordLoading').hidden,true);assert.equal(t.sibling.inert,false);
});
test('stop stays locked through finish and unlocks after completion',async()=>{
  const t=setup('recording');let finish;
  t.ctx.waitForFinishThenLoad=()=>new Promise(resolve=>{finish=resolve;});
  const first=t.element('stopConfirm').onclick();await Promise.resolve();await t.element('stopConfirm').onclick();
  assert.equal(t.requests,1);t.resolve({ok:true,id:'session'});
  await Promise.resolve();await Promise.resolve();
  assert.equal(t.element('recordLoading').hidden,false);finish();await first;
  assert.equal(t.element('recordLoading').hidden,true);assert.equal(t.element('stopConfirm').disabled,false);
});
test('stop failure restores controls',async()=>{
  const t=setup('recording');const first=t.element('stopConfirm').onclick();await Promise.resolve();t.reject(new Error('offline'));await first;
  assert.equal(t.element('recordLoading').hidden,true);assert.equal(t.element('stopConfirm').disabled,false);assert.equal(t.tick,null);
});
test('inline scripts parse',()=>{
  for(const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
});
