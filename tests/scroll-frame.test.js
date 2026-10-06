const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function harness(){
 const source=html.match(/function scrollFrameUpdate\(update\)\{[\s\S]*?\n\}/);
 assert.ok(source,'scroll updates need a frame scheduler');
 const frames=[];
 const context=vm.createContext({requestAnimationFrame:callback=>frames.push(callback)});
 vm.runInContext(source[0],context);
 return {schedule:context.scrollFrameUpdate,frames};
}
test('a burst updates once per frame using the latest scroll position',()=>{
 const {schedule,frames}=harness();let position=0;const updates=[];
 const listener=schedule(()=>updates.push(position));
 for(let i=0;i<100;i++){position=i;listener();}
 assert.equal(frames.length,1);assert.deepEqual(updates,[]);
 frames.shift()();assert.deepEqual(updates,[99]);
 position=150;listener();frames.shift()();assert.deepEqual(updates,[99,150]);
});
test('containers schedule independently and allow a following frame during update',()=>{
 const {schedule,frames}=harness();let updates=0;
 const listener=schedule(()=>{updates++;if(updates===1)listener();});
 const other=schedule(()=>{});
 listener();other();assert.equal(frames.length,2);
 frames.shift()();assert.equal(frames.length,2);
 frames.shift()();frames.shift()();assert.equal(updates,2);
});
test('pending updates read current project and drag state rather than retaining old state',()=>{
 const {schedule,frames}=harness();let project='old',drag=true;const updates=[];
 const listener=schedule(()=>updates.push([project,drag]));
 listener();project='new';drag=false;frames.shift()();
 assert.deepEqual(updates,[['new',false]]);
});
test('all three scroll listeners use frame scheduling and passive events',()=>{
 assert.match(html,/\$\('setBody'\)\.addEventListener\('scroll', scrollFrameUpdate\(\(\)=>\{[\s\S]*?\}\),\{passive:true\}\);/);
 assert.match(html,/\$\('feedwrap'\)\.addEventListener\('scroll',scrollFrameUpdate\(\(\)=>\{[\s\S]*?\}\),\{passive:true\}\);/);
 assert.match(html,/\$\('feedwrap'\)\.addEventListener\('scroll',scrollFrameUpdate\(updateTranscriptAnchorFromScroll\),\{passive:true\}\);/);
});
