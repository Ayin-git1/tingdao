const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function helper(name){
  const source=html.match(new RegExp(`function ${name}\\([^]*?\\n\\}`));
  assert.ok(source,`${name} exists`);
  return Function(`${source[0]}; return ${name}`)();
}

function appendHarness(count,{rowCost=0.05}={}){
  const appended=[],timers=[],observed=[],rows=[];let clock=0,done=0,current=true;
  const context=vm.createContext({
    $:()=>({appendChild(node){appended.push(node.items.length);}}),
    document:{createDocumentFragment:()=>({items:[]})},
    performance:{now:()=>clock},setTimeout:fn=>timers.push(fn),
    transcriptNearObserver:{observe(row){observed.push(row);},disconnect(){observed.length=0;}},
    transcriptNearBuckets:new Map(),
    addSeg(item,live,parent){
      clock+=rowCost;
      const row={dataset:{raw:item.text},classes:[],props:{},classList:{add(name){row.classes.push(name);}},style:{setProperty(k,v){row.props[k]=v;}}};
      parent.items.push(row);rows.push(row);return row;
    },
    addTranscriptHeading(item,parent){parent.items.push(item);},
    TRANSCRIPT_LAZY_PAINT_MIN:300,TRANSCRIPT_FIRST_ROWS:40,TRANSCRIPT_CHUNK_MS:4,TRANSCRIPT_NEAR_BUCKET:20,
    transcriptLineMetrics:()=>({lineHeight:28,columnWidth:400,charWidth:16}),
    transcriptSegmentHeight:helper('transcriptSegmentHeight'),
  });
  const source=html.match(/function appendTranscriptItems\([^]*?\n\}/)[0];
  vm.runInContext(source,context);
  const items=Array.from({length:count},(_,i)=>({type:'seg',t:i,text:'字'.repeat(i%3*40)}));
  const run=()=>context.appendTranscriptItems(items,()=>current,()=>done++);
  const drain=()=>{while(timers.length)timers.shift()();};
  return {run,drain,appended,timers,observed,rows,context,
    get done(){return done;},stop(){current=false;}};
}

test('a long transcript paints the first screen synchronously and appends the rest in time-boxed chunks',()=>{
  const h=appendHarness(400);
  h.run();
  assert.deepEqual(h.appended,[40]);
  assert.equal(h.done,0,'notes and time index wait for the last chunk');
  h.drain();
  assert.equal(h.rows.length,400);
  assert.ok(h.appended.slice(1).every(n=>n<=81),`chunks ${h.appended}`);
  assert.equal(h.done,1);
  assert.ok(h.rows.every(row=>row.classes.includes('lazy-seg')));
  assert.equal(h.rows[0].props['--seg-h'],'38px');   // 空句仍占一行
  assert.equal(h.rows[2].props['--seg-h'],'122px');  // 80 字 / 每行 25 字 = 4 行
});

test('one sentinel per 20 rows drives look-ahead rendering for its whole bucket',()=>{
  const h=appendHarness(400);
  h.run();h.drain();
  assert.equal(h.observed.length,20);
  const buckets=[...h.context.transcriptNearBuckets.values()];
  assert.ok(buckets.every(rows=>rows.length===20));
  assert.equal(buckets[3][0],h.observed[3]);
});

test('switching documents mid-load stops the remaining chunks',()=>{
  const h=appendHarness(400);
  h.run();h.stop();h.drain();
  assert.equal(h.rows.length,40);
  assert.equal(h.done,0);
});

test('short transcripts render in one synchronous pass with normal painting',()=>{
  const h=appendHarness(20,{rowCost:5});
  h.run();
  assert.deepEqual(h.appended,[20]);
  assert.equal(h.done,1);
  assert.equal(h.timers.length,0);
  assert.equal(h.observed.length,0);
  assert.ok(h.rows.every(row=>!row.classes.length&&!Object.keys(row.props).length));
});

test('look-ahead class does not invalidate cached paragraph positions',()=>{
  const changed=helper('transcriptLayoutChanged');
  const record={type:'attributes',attributeName:'class',oldValue:'seg lazy-seg',target:{getAttribute:()=>'seg lazy-seg cv-near'}};
  assert.equal(changed([record]),false);
});

test('placeholder height grows by whole lines and survives degenerate metrics',()=>{
  const height=helper('transcriptSegmentHeight');
  assert.equal(height(25,{lineHeight:28,columnWidth:400,charWidth:16}),38);
  assert.equal(height(26,{lineHeight:28,columnWidth:400,charWidth:16}),66);
  assert.equal(height(3,{lineHeight:28,columnWidth:0,charWidth:0}),94);
});

test('lazy painting skips rows whose content overflows or is being edited',()=>{
  const rule=html.match(/#feed \.seg\.lazy-seg([^{]*)\{([^}]*)\}/);
  assert.ok(rule,'lazy row rule exists');
  assert.match(rule[1],/:not\(\.image-aside-row\)/);
  assert.match(rule[1],/:not\(\[data-edit\]\)/);
  assert.match(rule[2],/content-visibility:auto;/);
  assert.match(rule[2],/contain-intrinsic-block-size:auto var\(--seg-h,/);
  assert.match(html,/#feed \.seg\.lazy-seg\.cv-near:not\(\.image-aside-row\):not\(\[data-edit\]\)\{content-visibility:visible;\}/);
});

test('even the first batch yields when expensive paragraphs exhaust the frame budget',()=>{
  const h=appendHarness(400,{rowCost:2});h.run();
  assert.ok(h.rows.length<=4,`first batch built ${h.rows.length} expensive rows`);
  assert.equal(h.done,0);h.drain();assert.equal(h.rows.length,400);assert.equal(h.done,1);
});

test('the completion promise settles when switching documents cancels pending chunks',async()=>{
  const h=appendHarness(400);const completion=h.run();h.stop();h.drain();
  assert.equal(await completion,false);assert.equal(h.done,0);
});
