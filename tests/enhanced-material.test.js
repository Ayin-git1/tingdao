const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');
const head = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const controls = html.slice(html.indexOf('const MATERIAL_MODES ='), html.indexOf('const THEME_PRESETS = {'));

function fixture(server = 'neutral', cached = 'true', rejectSave = false, options = null) {
  const storage = new Map([['tingdao-enhanced-material', cached]]);
  const css = {};
  const root = {dataset:{},style:{setProperty(key,value){css[key]=value;},removeProperty(key){delete css[key];}}};
  const button = {disabled:false,setAttribute(key,value){this[key]=value;},addEventListener(event,handler){this[event]=handler;}};
  const caption = {};
  const elements = Object.fromEntries(['materialAdjustments','materialBlur','materialBlurValue','materialTransparency','materialTransparencyValue','materialFilmLabel','materialShadowStrength','materialShadowStrengthValue','materialHighlightBloomRow','materialHighlightBloom','materialHighlightBloomValue','materialHighlightRow','materialHighlightStrength','materialHighlightStrengthValue','materialOpticsRow','materialOptics','materialRefractionRow','materialRefraction'].map(id=>[id,{setAttribute(key,value){this[key]=value;},addEventListener(event,handler){this[event]=handler;}}]));
  const saves = [];
  const context = vm.createContext({window:{matchMedia:()=>({matches:false,addEventListener(){}})},
    document:{documentElement:root},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    $:id=>id==='setMaterialMode'?button:id==='materialPreviewCaption'?caption:elements[id],
    savePersonalSetting:async (key,value)=>{saves.push({key,value});if(rejectSave)throw Error('failed');},toast(){}});
  vm.runInContext(head.replace('__TINGDAO_MATERIAL_MODE__', server).replace('__TINGDAO_MATERIAL_OPTIONS__',JSON.stringify(JSON.stringify(options))), context);
  vm.runInContext(controls, context);
  return {context, root, button, caption, storage, saves, elements, css};
}

test('saved mode wins over legacy cache before paint',()=>{
  assert.equal(fixture('neutral','true').root.dataset.material,'neutral');
  assert.equal(fixture('mimetic','false').button['aria-valuetext'],'拟态');
  assert.equal(fixture('__TINGDAO_MATERIAL_MODE__','true').root.dataset.material,'enhanced');
  assert.equal(fixture('__TINGDAO_MATERIAL_MODE__','false').root.dataset.material,'neutral');
});
test('three slider stops preview immediately and persist after change',async()=>{
  const f=fixture();
  for(const [index,mode,label] of [[1,'enhanced','增强'],[2,'mimetic','拟态'],[0,'neutral','中性']]){
    f.button.input({target:{value:String(index)}});
    assert.equal(f.root.dataset.material,mode);
    assert.equal(f.caption.textContent,`${label}材质`);
    assert.equal(f.button['aria-valuetext'],label);
    assert.equal(f.storage.get('tingdao-material-mode'),mode);
    await f.button.change();
  }
  assert.deepEqual(f.saves,['enhanced','mimetic','neutral'].map(value=>({key:'material_mode',value})));
  assert.equal(f.button.disabled,false);
});
test('save failure restores last saved mode, preview, slider and cache',async()=>{
  const f=fixture('enhanced','false',true);
  f.button.input({target:{value:'2'}});
  await f.button.change();
  assert.equal(f.root.dataset.material,'enhanced');
  assert.equal(f.button.value,1);
  assert.equal(f.button['aria-valuetext'],'增强');
  assert.equal(f.caption.textContent,'增强材质');
  assert.equal(f.storage.get('tingdao-material-mode'),'enhanced');
  assert.equal(f.button.disabled,false);
});
test('material modes preserve blur, with specular shadows only for mimetic',()=>{
  const rules=html.match(/(?<!,)html(?:\[data-appearance="dark"\])?\[data-material="(?:enhanced|mimetic)"\] \{[^}]+\}/g);
  assert.equal(rules.length,4);
  for(const rule of rules){
    assert.match(rule,/--material-rest-background:linear-gradient/);
    assert.match(rule,/--material-expanded-background:linear-gradient/);
    assert.doesNotMatch(rule,/135deg|transparent|backdrop-filter|filter:/);
    if(rule.includes('data-material="mimetic"')){
      assert.match(rule,/--material-specular-edge:inset 0 1px 1px/);
      assert.match(rule,/inset 1px 0 1px/);
      assert.doesNotMatch(rule,/inset [^;]*rgba\(0,0,0/);
      for(const level of [1,2,3]) assert.ok(rule.includes(`--material-shadow-level-${level}:var(--material-specular-edge),0`));
      assert.match(rule,rule.includes('data-appearance="dark"')
        ? /rgba\(var\(--g-rgb\),calc\(\.025 \* var\(--material-shadow-strength,1\)\)\)/
        : /rgba\(var\(--g-rgb\),calc\(\.10 \* var\(--material-shadow-strength,1\)\)\)/);
    }else assert.match(rule,/0 4px 10px rgba\(var\(--g-rgb\),calc\(\.13 \* var\(--material-shadow-strength,1\)\)\)/);
    const tints = [...rule.matchAll(/linear-gradient\(rgba\(var\(--g-rgb\),([.\d]+)\),rgba\(var\(--g-rgb\),([.\d]+)\)\)/g)];
    assert.equal(tints.length,rule.includes('data-appearance="dark"') ? 0 : 2);
    for(const tint of tints) assert.equal(tint[1],tint[2], 'theme tint is uniform without side glare');
  }
  assert.ok(html.indexOf('class="material-preview"')<html.indexOf('id="setMaterialMode"'));
  const backend=fs.readFileSync('app.py','utf8');
  assert.match(backend,/"__TINGDAO_MATERIAL_MODE__", material_mode/);
  assert.match(backend,/material_mode = "enhanced" if load_setting\("enhanced_material"\) is True else "neutral"/);
});
test('dark material softens the white film and inner highlights',()=>{
  const darkEnhanced=html.match(/html\[data-appearance="dark"\]\[data-material="enhanced"\] \{[^}]+\}/)?.[0];
  const darkMimetic=html.match(/html\[data-appearance="dark"\]\[data-material="mimetic"\] \{[^}]+\}/)?.[0];
  assert.ok(darkEnhanced && darkMimetic);
  assert.match(darkEnhanced,/rgba\(255,255,255,\.008\)/);
  assert.match(darkEnhanced,/inset 0 1px 0 rgba\(255,255,255,\.035\)/);
  assert.match(darkMimetic,/rgba\(255,255,255,\.008\)/);
  assert.match(darkMimetic,/rgba\(64,64,64,var\(--material-custom-opacity,\.24\)\)/);
  assert.match(darkMimetic,/rgba\(255,255,255,calc\(\.07 \* var\(--material-highlight-strength,1\)\)\)/);
  assert.match(darkMimetic,/rgba\(255,255,255,calc\(0\.02 \* var\(--material-highlight-bloom-strength,0\)\)\)/);
  assert.match(html,/index === 1 \? \(dark \? 45 : 54\) : 76/);
});
test('dark materials remove background tint while retaining themed shadows',()=>{
  const darkRules=html.match(/html\[data-appearance="dark"\](?:\[data-material="(?:enhanced|mimetic)"\])? \{[^}]+\}/g);
  assert.equal(darkRules.length,3);
  for(const rule of darkRules){
    for(const background of rule.matchAll(/--material-(?:rest|expanded)-background:([^;]+);/g))
      assert.doesNotMatch(background[1],/--g-rgb/);
  }
  const darkMimetic=html.match(/html\[data-appearance="dark"\]\[data-material="mimetic"\] \{[^}]+\}/)?.[0];
  assert.ok(darkMimetic);
  assert.match(darkMimetic,/rgba\(var\(--g-rgb\),calc\(\.025 \* var\(--material-shadow-strength,1\)\)\)/);
  assert.match(darkMimetic,/rgba\(var\(--g-rgb\),calc\(\.055 \* var\(--material-shadow-strength,1\)\)\)/);
});

test('dark theme preserves the saved blue-green base lightness',()=>{
  const css = {};
  const root = {dataset:{},style:{setProperty(key,value){css[key]=value;},removeProperty(key){delete css[key];}}};
  const storage = new Map();
  const context = vm.createContext({
    window:{matchMedia:()=>({matches:false,addEventListener(){}})},
    document:{documentElement:root},
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}
  });
  const theme = {h:169.91039663215656,s:51,l:44};
  const options = {enhanced:{},mimetic:{}};
  const source = head
    .replace('__TINGDAO_APPEARANCE__','dark')
    .replace('__TINGDAO_MATERIAL_MODE__','mimetic')
    .replace('__TINGDAO_THEME_COLOR__',JSON.stringify(JSON.stringify(theme)))
    .replace('__TINGDAO_MATERIAL_OPTIONS__',JSON.stringify(JSON.stringify(options)));
  vm.runInContext(source, context);
  assert.equal(root.dataset.appearance,'dark');
  assert.equal(css['--g-rgb'],'55, 169, 150');
  assert.equal(css['--g'],'hsl(169.91039663215656 51% 44%)');
});

test('visual controls are hidden for neutral and remember each material independently',async()=>{
  const f=fixture();
  assert.equal(f.elements.materialAdjustments.hidden,true);
  f.button.input({target:{value:'1'}});
  assert.equal(f.elements.materialAdjustments.hidden,false);
  assert.equal(f.elements.materialTransparency.value,54);
  f.elements.materialBlur.input({target:{value:'12'}});
  await f.elements.materialBlur.change();
  f.elements.materialTransparency.input({target:{value:'85'}});
  await f.elements.materialTransparency.change();
  assert.equal(f.css['--material-custom-blur'],'12px');
  assert.equal(f.css['--material-custom-opacity'],'0.15');
  f.button.input({target:{value:'2'}});
  assert.equal(f.elements.materialBlur.value,4);
  assert.equal(f.elements.materialTransparency.value,76);
  f.button.input({target:{value:'1'}});
  assert.equal(f.elements.materialBlur.value,12);
  assert.equal(f.elements.materialTransparency.value,85);
  f.button.input({target:{value:'0'}});
  assert.equal(f.elements.materialAdjustments.hidden,true);
  assert.equal(f.css['--material-custom-blur'],undefined);
});
test('visual save failure restores saved values and reenables controls',async()=>{
  const f=fixture('enhanced','false',true);
  f.elements.materialBlur.input({target:{value:'18'}});
  await f.elements.materialBlur.change();
  assert.equal(f.elements.materialBlur.value,4);
  assert.equal(f.css['--material-custom-blur'],'4px');
  assert.equal(f.elements.materialBlur.disabled,false);
  assert.equal(f.button.disabled,false);
});

test('saved visual settings are applied before paint, including zero and full transparency',()=>{
  const f=fixture('mimetic','false',false,{enhanced:{blur:19,transparency:10},mimetic:{blur:0,transparency:100}});
  assert.equal(f.css['--material-custom-blur'],'0px');
  assert.equal(f.css['--material-custom-opacity'],'0');
  assert.equal(f.elements.materialTransparency.value,100);
  f.button.input({target:{value:'1'}});
  assert.equal(f.css['--material-custom-blur'],'19px');
  assert.equal(f.css['--material-custom-opacity'],'0.9');
});

test('shadow concentration previews independently and persists for each material',async()=>{
  const f=fixture('enhanced','false');
  assert.equal(f.elements.materialShadowStrength.value,50);
  f.elements.materialShadowStrength.input({target:{value:'20'}});
  await f.elements.materialShadowStrength.change();
  assert.equal(f.css['--material-shadow-strength'],'0.4');
  f.button.input({target:{value:'2'}});
  assert.equal(f.elements.materialShadowStrength.value,50);
  f.elements.materialShadowStrength.input({target:{value:'0'}});
  await f.elements.materialShadowStrength.change();
  assert.equal(f.css['--material-shadow-strength'],'0');
  f.button.input({target:{value:'1'}});
  assert.equal(f.elements.materialShadowStrength.value,20);
  assert.equal(f.css['--material-shadow-strength'],'0.4');
  f.button.input({target:{value:'0'}});
  assert.equal(f.css['--material-shadow-strength'],undefined);
});

test('inner highlight control is mimetic-only and changes independently of shadow',async()=>{
  const f=fixture('enhanced','false');
  assert.equal(f.elements.materialHighlightRow.hidden,true);
  f.button.input({target:{value:'2'}});
  assert.equal(f.elements.materialHighlightRow.hidden,false);
  assert.equal(f.elements.materialHighlightStrength.value,50);
  f.elements.materialHighlightStrength.input({target:{value:'0'}});
  await f.elements.materialHighlightStrength.change();
  assert.equal(f.css['--material-highlight-strength'],'0');
  assert.equal(f.css['--material-shadow-strength'],'1');
  assert.equal(f.saves.at(-1).value.mimetic.highlightStrength,0);
  f.button.input({target:{value:'0'}});
  assert.equal(f.elements.materialHighlightRow.hidden,true);
  assert.equal(f.css['--material-highlight-strength'],undefined);
  f.button.input({target:{value:'2'}});
  assert.equal(f.elements.materialHighlightStrength.value,0);
});
test('inward bloom is opt-in, mimetic-only, saved independently of the highlight strip',async()=>{
  const f=fixture('enhanced','false');
  assert.equal(f.elements.materialHighlightBloomRow.hidden,true);
  f.button.input({target:{value:'2'}});
  assert.equal(f.elements.materialHighlightBloomRow.hidden,false);
  assert.equal(f.elements.materialHighlightBloom.value,0);
  f.elements.materialHighlightBloom.input({target:{value:'75'}});
  await f.elements.materialHighlightBloom.change();
  assert.equal(f.css['--material-highlight-bloom-strength'],'0.75');
  assert.equal(f.css['--material-highlight-strength'],'1');
  assert.equal(f.css['--material-shadow-strength'],'1');
  assert.equal(f.saves.at(-1).value.mimetic.highlightBloom,75);
  const restored=fixture('mimetic','false',false,f.saves.at(-1).value);
  assert.equal(restored.elements.materialHighlightBloom.value,75);
  f.button.input({target:{value:'1'}});
  assert.equal(f.elements.materialHighlightBloomRow.hidden,true);
  assert.equal(f.css['--material-highlight-bloom-strength'],'0');
  f.button.input({target:{value:'0'}});
  assert.equal(f.css['--material-highlight-bloom-strength'],undefined);
});
test('inward bloom save failure restores the previous value',async()=>{
  const f=fixture('mimetic','false',true);
  f.elements.materialHighlightBloom.input({target:{value:'100'}});
  await f.elements.materialHighlightBloom.change();
  assert.equal(f.elements.materialHighlightBloom.value,0);
  assert.equal(f.elements.materialHighlightBloom.disabled,false);
});
test('inner highlight save failure restores the previous value',async()=>{
  const f=fixture('mimetic','false',true);
  f.elements.materialHighlightStrength.input({target:{value:'100'}});
  await f.elements.materialHighlightStrength.change();
  assert.equal(f.elements.materialHighlightStrength.value,50);
  assert.equal(f.css['--material-highlight-strength'],'1');
  assert.equal(f.elements.materialHighlightStrength.disabled,false);
});

test('optical enhancement is opt-in, mimetic-only, and restored before paint',async()=>{
  const f=fixture('mimetic','false');
  assert.equal(f.elements.materialOptics.checked,false);
  assert.equal(f.elements.materialOpticsRow.hidden,false);
  f.elements.materialOptics.input({target:{checked:true}});
  await f.elements.materialOptics.change();
  assert.equal(f.root.dataset.glassOptics,'on');
  assert.equal(f.saves.at(-1).value.mimetic.opticalEnhancement,true);
  const restored=fixture('mimetic','false',false,f.saves.at(-1).value);
  assert.equal(restored.root.dataset.glassOptics,'on');
  for(const index of [0,1]){
    f.button.input({target:{value:String(index)}});
    assert.equal(f.root.dataset.glassOptics,'off');
    assert.equal(f.elements.materialOpticsRow.hidden,true);
  }
  f.button.input({target:{value:'2'}});
  assert.equal(f.root.dataset.glassOptics,'on');
  assert.equal(f.elements.materialOptics.checked,true);
  f.elements.materialOptics.input({target:{checked:false}});
  await f.elements.materialOptics.change();
  assert.equal(f.root.dataset.glassOptics,'off');
});

test('failed optical enhancement save rolls back the switch and material',async()=>{
  const f=fixture('mimetic','false',true);
  f.elements.materialOptics.input({target:{checked:true}});
  await f.elements.materialOptics.change();
  assert.equal(f.root.dataset.glassOptics,'off');
  assert.equal(f.elements.materialOptics.checked,false);
  assert.equal(f.elements.materialOptics.disabled,false);
});

test('SVG refraction is independent, saved, and limited to mimetic',async()=>{
  const f=fixture('mimetic','false');
  assert.equal(f.elements.materialRefraction.checked,false);
  f.elements.materialRefraction.input({target:{checked:true}});
  await f.elements.materialRefraction.change();
  assert.equal(f.root.dataset.glassRefraction,'on');
  assert.equal(f.root.dataset.glassOptics,'off');
  const restored=fixture('mimetic','false',false,f.saves.at(-1).value);
  assert.equal(restored.root.dataset.glassRefraction,'on');
  f.button.input({target:{value:'1'}});
  assert.equal(f.root.dataset.glassRefraction,'off');
  assert.equal(f.elements.materialRefractionRow.hidden,true);
  f.button.input({target:{value:'2'}});
  assert.equal(f.elements.materialRefraction.checked,true);
});

test('SVG save failure restores the switch and filter state',async()=>{
  const f=fixture('mimetic','false',true);
  f.elements.materialRefraction.input({target:{checked:true}});
  await f.elements.materialRefraction.change();
  assert.equal(f.root.dataset.glassRefraction,'off');
  assert.equal(f.elements.materialRefraction.checked,false);
  assert.equal(f.elements.materialRefraction.disabled,false);
});

test('material preview uses the bundled lakeside image and server route',()=>{
  assert.match(html,/\.material-preview\{[^}]*background-image:url\('\/material-preview\/lakeside\.png'\)/);
  assert.ok(fs.existsSync('assets/material-preview-lakeside.png'));
  assert.ok(fs.statSync('assets/material-preview-lakeside.png').size > 100000);
  const backend=fs.readFileSync('app.py','utf8');
  assert.match(backend,/u\.path == "\/material-preview\/lakeside\.png"/);
  const tauri=fs.readFileSync('tauri-shell/tauri.conf.json','utf8');
  assert.match(tauri,/material-preview-lakeside\.png/);
});
