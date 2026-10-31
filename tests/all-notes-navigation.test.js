const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const html=fs.readFileSync('index.html','utf8');
const source=name=>{const start=html.indexOf(`function ${name}(`);assert.ok(start>=0,`${name} exists`);return html.slice(start,html.indexOf('\n}',start)+2);};

test('note navigation corrects lazy layout shifts and suppresses playback following',()=>{
  let offset=4000,scrolls=0,held=false;const frames=new Map();let frameId=0;
  const target={isConnected:true,scrollIntoView(){offset=0;scrolls++;}};
  const context=vm.createContext({
    $:()=>({querySelector:()=>target}),markUserScroll:()=>{held=true;},
    requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId;},cancelAnimationFrame:id=>frames.delete(id),
  });
  vm.runInContext('let noteJumpFrame=null;\n'+source('scrollToTimelineNote'),context);
  context.scrollToTimelineNote(2);
  let count=0;
  while(frames.size){const [id,fn]=frames.entries().next().value;frames.delete(id);if(count++<3)offset+=500;fn();assert.ok(count<20,'correction is bounded');}
  assert.equal(offset,0,'note stays centered after paragraphs above it are laid out');
  assert.ok(scrolls>1);assert.equal(held,true);
  context.scrollToTimelineNote(4);context.scrollToTimelineNote(7);
  assert.equal(frames.size,1,'a new jump cancels the previous correction');
  target.isConnected=false;const before=scrolls;
  for(const fn of frames.values())fn();
  assert.equal(scrolls,before,'leaving the transcript stops correction');
});

test('all-notes click uses the corrected navigation path',()=>{
  assert.match(source('renderAllNotes'),/scrollToTimelineNote\(index\)/);
});
