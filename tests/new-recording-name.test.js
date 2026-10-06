const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const start=html.indexOf("$('fab').onclick = async ()=>{");
const source=html.slice(start,html.indexOf('\n};',start)+3);
function harness(view){
 const elements=new Map(),calls=[];
 const $=id=>{if(!elements.has(id))elements.set(id,{value:'上一个改名项目',style:{},classList:{add(){},remove(){}}});return elements.get(id);};
 const context=vm.createContext({transcriptViewGeneration:0,updateRefineUI(){},$,state:'idle',view,selected:new Set(),renderSelState(){},defaultName:()=> '新录音 当前时间',
  api:async(path,body)=>{calls.push({path,body});return {ok:true};},mode:'mic',langSel:'zh',sessionName:'上一个改名项目',
  exitView(){context.view=null;$('nameInput').value='上一个改名项目';},resetPlaybackSegments(){},pumpTimer:null,updateChrome(){},toast(){}});
 vm.runInContext(source,context);return {context,elements,calls,$};
}
test('new recording after rename uses current time rather than previous title',async()=>{
 const {context,calls,$}=harness(null);await $('fab').onclick();
 assert.equal(calls[0].body.name,'新录音 当前时间');assert.equal(context.sessionName,'新录音 当前时间');
 assert.equal($('nameInput').value,'新录音 当前时间');
 assert.equal(context.state,'recording');assert.equal(context.view,null);
 assert.equal($('feed').style.opacity,'');
});
test('new recording from an opened manuscript also generates a fresh name',async()=>{
 const {calls,$}=harness({id:'old',name:'旧文稿'});await $('fab').onclick();
 assert.equal(calls[0].body.name,'新录音 当前时间');
});
test('each successive recording obtains a new default name',async()=>{
 const {context,calls,$}=harness(null);await $('fab').onclick();
 context.defaultName=()=> '新录音 下一时间';context.state='idle';$('nameInput').value='再次改名';
 await $('fab').onclick();assert.equal(calls[1].body.name,'新录音 下一时间');
});
