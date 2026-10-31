const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function blockBetween(start, end) {
  const from = html.indexOf(start);
  const to = html.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing block: ${start}`);
  return html.slice(from, to);
}

test('refine status uses a quiet top card with fixed copy and three loading dots', () => {
  const card = blockBetween('<div class="refine-card"', '\n    </div>');
  assert.match(card, /class="refine-card"/);
  assert.match(card, /文稿精修中/);
  assert.match(card, /完成后可生成 AI 摘要/);
  assert.match(card, /class="refine-dots"[\s\S]*?<i class="refine-dot"><\/i>[\s\S]*?<i class="refine-dot"><\/i>[\s\S]*?<i class="refine-dot"><\/i>/);
  assert.match(card, /id="btnGenerateSummary"[^>]*hidden/);
  assert.doesNotMatch(card, /refineStageTxt|精修阶段|\b\d+%/);
});

test('summary banner follows the todo list language in both appearances and respects reduced motion', () => {
  assert.match(html, /\.refine-card\{[^}]*border-bottom:1px solid var\(--line\)[^}]*background:none[^}]*box-shadow:none/);
  assert.match(html, /\.refine-icon circle\{[^}]*stroke-dasharray/);
  assert.match(html, /id="btnGenerateSummary"[^>]*>[\s\S]*?class="refine-spark"[\s\S]*?>摘要</);
  assert.match(html, /html\[data-appearance="dark"\] \.refine-card\{--refine-err:/);
  assert.match(html, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.refine-icon circle[^{]*\{animation:none/);
});

test('refine jobs toggle the card without exposing stage text or percentage in it', () => {
  const update = blockBetween('function updateRefineUI(){', '\n}\n\n/* 后台停止入口');
  assert.match(update, /\$\('refinewrap'\)\.classList\.toggle\('show', showing\)/);
  assert.doesNotMatch(update, /refineStageTxt|refineStageText\(|refinePct/);
});

test('completed short manuscripts show the summary action while empty or busy projects do not',()=>{
 const vm=require('node:vm');
 const source=blockBetween('function updateRefineUI(){','/* 后台停止入口');
 for(const scenario of [
  {segments:[{text:'一段正文'}],refinished:'whisper',show:true},
  {segments:[{text:'第一段'},{text:'第二段'}],refinished:'whisper',show:true},
  {segments:[],refinished:'whisper',show:false},
  {segments:[{text:'正文'}],show:false},
  {segments:[{text:'正文'}],refinished:'whisper',summary:'已有摘要',show:false},
  {segments:[{text:'正文'}],refinished:'whisper',job:{state:'run',kind:'refine'},show:false},
 ]){
  const elements=new Map();const $=id=>{
   if(!elements.has(id))elements.set(id,{style:{},classList:{toggle(){},remove(){}},setAttribute(){}});
   return elements.get(id);
  };
  const ctx=vm.createContext({$,view:{id:'s',...scenario},jobs:scenario.job?{s:scenario.job}:{},document:{querySelector:()=>$('topbar')},todoDone:null,paintTodo(){}});
  vm.runInContext(source,ctx);ctx.updateRefineUI();
  assert.equal($('btnGenerateSummary').hidden,!scenario.show);
 }
});
