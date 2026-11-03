const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('index.html', 'utf8');
function harness({home=false, count=4042}={}) {
  const classes=new Set(home?['home']:[]), properties=new Map(), calls=[];
  const feed={children:{length:count},offsetTop:0,
    getBoundingClientRect(){calls.push('measure');return {width:885.5,height:146309};},
    style:{setProperty(key,value){properties.set(key,value);calls.push('freeze');}}};
  const elements={feed,feedwrap:{offsetTop:90},hpGrid:{style:{display:'block'},offsetTop:15},skel:{style:{}}};
  const document={body:{classList:{contains:key=>classes.has(key),add(key){calls.push('mask');classes.add(key);}}}};
  const source=html.match(/function skelActivate\(\)\{[\s\S]*?\n\}/)[0];
  const frozen=[];
  const activate=Function('document','$','prepareTranscriptSkeleton','freezeHomeGrid',`${source}; return skelActivate;`)(document,id=>elements[id],()=>{},grid=>frozen.push(grid));
  return {activate,properties,calls,classes,elements,frozen};
}
test('long transcript geometry is frozen before sidebar animation can resize the parent', () => {
  const h=harness();
  assert.equal(h.activate(),true);
  assert.equal(h.properties.get('--side-feed-width'),'885.5px');
  // 宽度和高度都在起步前量好: 推挤期间正文跳过排版(content-visibility), 高度靠这个值占住
  assert.equal(h.properties.get('--side-feed-height'),'146309px');
  assert.deepEqual(h.calls,['measure','freeze','freeze','mask']);
  assert.equal(h.elements.skel.style.top,'90px');
  // A rapid reversal must refresh the same snapshot rather than accumulate styles or nodes.
  h.activate();
  assert.equal(h.properties.size,2);
  assert.equal(h.frozen.length,0);
});
test('home cards and empty transcripts do not acquire transcript width constraints', () => {
  const home=harness({home:true});
  assert.equal(home.activate(),true);
  assert.equal(home.properties.size,0);
  // 主页不盖骨架、不隐身卡片(否则文字一闪), 只锁住列数让卡片随主区伸缩
  assert.deepEqual(home.frozen,[home.elements.hpGrid]);
  assert.equal(home.classes.has('side-skel'),false);
  const empty=harness({count:0});
  assert.equal(empty.activate(),false);
  assert.equal(empty.properties.size,0);
  assert.equal(empty.classes.has('side-skel'),false);
});

test('home cards stay visible while the sidebar pushes, then slide to the new column layout', () => {
  // 父级 opacity<1 会让卡片玻璃退化成实心底色; 主页也不再淡出卡片文字
  assert.doesNotMatch(html, /#hpGrid\{opacity:0;\}|#hpGrid > \*\{opacity:0;\}|sk-home/);
  // 起步就排成落定后的列数/卡宽, 卡片与侧栏同曲线同时长过渡过去, 不被硬挤
  assert.match(html, /function freezeHomeGrid\(grid\)\{[\s\S]*?showing \? -291 : 291/);
  assert.match(html, /toggle\('sidehide'\);\s*flipHomeGrid\(580, \[\.32,0,\.14,1\]\)/);
  assert.match(html, /remove\('sidehide'\);\s*flipHomeGrid\(520, \[\.16,1,\.3,1\]\)/);
  // 卡片坐标每帧由 rAF 按网格原点反推, 不交给合成器线程的 WAAPI(会和主区左缘错帧)
  assert.doesNotMatch(html.match(/function flipHomeGrid[\s\S]*?\n\}/)[0], /\.animate\(/);
  assert.match(html, /classList\.remove\('side-skel'\);\s*releaseHomeGrid\(\);/);
  assert.match(html, /body\.side-promoting:not\(\.home\) \.feedzone\{animation:sideTextMask/);
});
