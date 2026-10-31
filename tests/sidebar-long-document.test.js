const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('index.html', 'utf8');
function harness({home=false, count=4042}={}) {
  const classes=new Set(home?['home']:[]), properties=new Map(), calls=[];
  const feed={children:{length:count},offsetTop:0,
    getBoundingClientRect(){calls.push('measure');return {width:885.5};},
    style:{setProperty(key,value){properties.set(key,value);calls.push('freeze');}}};
  const elements={feed,feedwrap:{offsetTop:90},hpGrid:{style:{display:'block'},offsetTop:15},skel:{style:{}}};
  const document={body:{classList:{contains:key=>classes.has(key),add(key){calls.push('mask');classes.add(key);}}}};
  const source=html.match(/function skelActivate\(\)\{[\s\S]*?\n\}/)[0];
  const activate=Function('document','$','prepareTranscriptSkeleton',`${source}; return skelActivate;`)(document,id=>elements[id],()=>{});
  return {activate,properties,calls,classes,elements};
}
test('long transcript geometry is frozen before sidebar animation can resize the parent', () => {
  const h=harness();
  assert.equal(h.activate(),true);
  assert.equal(h.properties.get('--side-feed-width'),'885.5px');
  assert.deepEqual(h.calls,['measure','freeze','mask']);
  assert.equal(h.elements.skel.style.top,'90px');
  // A rapid reversal must refresh the same snapshot rather than accumulate styles or nodes.
  h.activate();
  assert.equal(h.properties.size,1);
});
test('home cards and empty transcripts do not acquire transcript width constraints', () => {
  const home=harness({home:true});
  assert.equal(home.activate(),true);
  assert.equal(home.properties.size,0);
  assert.equal(home.elements.skel.style.top,'105px');
  const empty=harness({count:0});
  assert.equal(empty.activate(),false);
  assert.equal(empty.properties.size,0);
  assert.equal(empty.classes.has('side-skel'),false);
});
