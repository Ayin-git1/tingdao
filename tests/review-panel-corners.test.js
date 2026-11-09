const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const html=fs.readFileSync('index.html','utf8');
const rule=sel=>html.match(new RegExp('\\n\\s*'+sel.replace('.','\\.')+'\\{([^}]*)\\}'))[1];
test('review panel views carry the panel radius so WebKit wheel scrolling keeps rounded corners',()=>{
  assert.match(rule('#reviewPanel'),/border-radius:var\(--radius-3\)/);
  for(const sel of ['.rv-views','.rv-view']) assert.match(rule(sel),/border-radius:inherit/,sel+' must inherit the panel radius');
  assert.match(rule('.rv-view'),/background:var\(--bg\)/);
});
