const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
function panel(save = async () => {}) {
  let click;
  const buttons = ['white', 'magazine'].map(v => ({dataset:{v}, disabled:false,
    classList:{toggle(_, selected){this.on = selected;}}, setAttribute(k,v){this[k] = v;}}));
  const seg = {querySelectorAll:()=>buttons, querySelector:()=>buttons.find(b=>b.classList.on),
    addEventListener:(_, fn)=>{click=fn;}};
  const context = vm.createContext({document:{documentElement:{dataset:{}}}, $:()=>seg,
    segInd:()=>{}, savePersonalSetting:save, toast:msg=>{context.message=msg;}});
  vm.runInContext(html.slice(html.indexOf("let summaryBackground = 'magazine';"),
    html.indexOf('const MATERIAL_MODES =')), context);
  return {context, buttons, apply:value=>context.applySummaryBackground(value),
    click:value=>click({target:{closest:()=>buttons.find(b=>b.dataset.v===value)}})};
}
test('missing or invalid preference defaults to magazine; saved white restores on reload', () => {
  for (const value of [undefined, 'invalid', 'magazine', 'white']) {
    const p = panel(); p.apply(value);
    assert.equal(p.context.document.documentElement.dataset.summaryBackground, value==='white'?'white':'magazine');
    assert.equal(p.buttons.filter(b=>b['aria-pressed']==='true').length, 1);
  }
  assert.match(html, /applySummaryBackground\(st.summary_background\)/);
});
test('switch applies immediately and saves through the existing persistent settings API', async () => {
  const writes=[]; const p=panel(async (key,value)=>writes.push({key,value}));
  p.apply('magazine'); await p.click('white');
  assert.equal(p.context.document.documentElement.dataset.summaryBackground, 'white');
  assert.deepEqual(writes,[{key:'summary_background',value:'white'}]);
  const reloaded=panel(); reloaded.apply(writes[0].value);
  assert.equal(reloaded.context.document.documentElement.dataset.summaryBackground, 'white');
  assert.ok(p.buttons.every(b=>!b.disabled));
});
test('failed save restores the previous background and control selection', async () => {
  const p=panel(async ()=>{throw new Error('offline');});
  p.apply('white'); await p.click('magazine');
  assert.equal(p.context.document.documentElement.dataset.summaryBackground, 'white');
  assert.equal(p.buttons[0]['aria-pressed'],'true');
  assert.ok(p.buttons.every(b=>!b.disabled));
  assert.match(p.context.message,/保存失败/);
});
