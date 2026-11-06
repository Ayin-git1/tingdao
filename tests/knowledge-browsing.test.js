const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function harness(reduced=false){
 const moves=[],viewport={scrollTop:0,clientHeight:500,scrollHeight:1900,scrollTo(o){moves.push(o);},scrollBy(o){this.scrollTop+=o.top;}};
 const ctx=vm.createContext({gr:{busy:false,tab:'knowledge',selected:'kept',page:0},$:id=>id==='grKnowledgeScroll'?viewport:null,matchMedia:()=>({matches:reduced}),grSyncKnowledgePager(){},grAll:()=>Array(13).fill({}),grFilter:r=>r,grRender(){}});
 const start=html.indexOf('function grTurnPage(delta){'),end=html.indexOf('function grRelatedText(row){');
 vm.runInContext(html.slice(start,end),ctx);return {ctx,viewport,moves};
}
test('page buttons move one viewport without changing the selected knowledge',()=>{
 const {ctx,viewport,moves}=harness();viewport.scrollTop=120;ctx.grTurnPage(1);
 assert.equal(moves.length,1);assert.equal(moves[0].top,556);assert.equal(moves[0].behavior,'smooth');assert.equal(ctx.gr.selected,'kept');
});
test('rapid paging uses the pending destination, clamps both ends and reverses',()=>{
 const {ctx,moves}=harness();ctx.grTurnPage(1);ctx.grTurnPage(1);ctx.grTurnPage(1);ctx.grTurnPage(1);ctx.grTurnPage(-1);ctx.grTurnPage(-20);
 assert.deepEqual(moves.map(m=>m.top),[436,872,1308,1400,964,0]);
});
test('reduced motion pages instantly and saving blocks page commands',()=>{
 const {ctx,moves}=harness(true);ctx.grTurnPage(1);assert.equal(moves[0].behavior,'instant');ctx.gr.busy=true;ctx.grTurnPage(1);assert.equal(moves.length,1);
});
test('horizontal gestures translate line and page deltas while vertical wheel and zoom remain native',()=>{
 const {ctx,viewport}=harness();const event=(x,y,mode=0)=>({deltaX:x,deltaY:y,deltaMode:mode,ctrlKey:false,defaultPrevented:false,target:{closest:()=>viewport},preventDefault(){this.defaultPrevented=true;}});
 let e=event(3,0,1);ctx.grKnowledgeWheel(e);assert.equal(viewport.scrollTop,72);assert.equal(e.defaultPrevented,true);
 e=event(1,0,2);ctx.grKnowledgeWheel(e);assert.equal(viewport.scrollTop,572);
 e=event(2,40);ctx.grKnowledgeWheel(e);assert.equal(e.defaultPrevented,false);assert.equal(viewport.scrollTop,572);
 e=event(10,0);e.ctrlKey=true;ctx.grKnowledgeWheel(e);assert.equal(e.defaultPrevented,false);assert.equal(viewport.scrollTop,572);
});
test('a chapter response refreshes the selected chapter in the same course after a fast switch',async()=>{
 let updates=0;const selected={key:'second',session:{id:'course'}},ctx=vm.createContext({gr:{open:true,tab:'knowledge',selected:'second',detailEpoch:0,detailLoading:'',detail:null},api:async()=>({id:'course',segments:[{t:10,text:'完整原文'}]}),grAll:()=>[selected],grUpdateReading:()=>updates++});
 vm.runInContext(html.slice(html.indexOf('async function grLoadDetail(row){'),html.indexOf('function grCompletion(){')),ctx);
 await ctx.grLoadDetail({key:'first',session:{id:'course'}});assert.equal(updates,1);assert.equal(ctx.gr.detail.id,'course');
});

test('a partially filled final viewport is labelled as the last page',()=>{
 const label={},buttons={'[data-gr-page="-1"]':{},'[data-gr-page="1"]':{}},viewport={scrollHeight:2487,clientHeight:696,scrollTop:1791,dataset:{count:23}};
 const ctx=vm.createContext({gr:{busy:false},$:id=>id==='grKnowledgeScroll'?viewport:id==='grPagePosition'?label:{querySelector:s=>buttons[s]}});
 vm.runInContext(html.slice(html.indexOf('function grSyncKnowledgePager(){'),html.indexOf('// 可用高度控制阅读框')),ctx);ctx.grSyncKnowledgePager();
 assert.equal(label.textContent,'4 / 4 页 · 23 条知识');assert.equal(buttons['[data-gr-page="-1"]'].disabled,false);assert.equal(buttons['[data-gr-page="1"]'].disabled,true);
});

function readingDetail(detail,row){
 const ctx=vm.createContext({gr:{detail},esc:String,queueMicrotask(){},reviewNotes:()=>[]});
 vm.runInContext(html.slice(html.indexOf('const GR_READING_LIMIT='),html.indexOf('async function grLoadDetail(row){')),ctx);
 return ctx.grDetailHtml(row);
}
const chapterRow={session:{id:'c'},item:{kind:'chap'},source:{t:0,end:100}};
const END='--- 回文稿继续看吧～ ---';
test('a chapter within the reading limit shows in full without the end hint',()=>{
 const out=readingDetail({id:'c',segments:[{t:1,text:'字'.repeat(800)}]},chapterRow);
 assert.ok(out.includes('字'.repeat(800)));assert.ok(!out.includes(END));
});
test('a long chapter stops at the last sentence and sends the reader back to the manuscript',()=>{
 const out=readingDetail({id:'c',segments:[{t:1,text:'字'.repeat(700)+'。'+'后'.repeat(400)}]},chapterRow);
 assert.ok(out.includes('字'.repeat(700)+'。</p>'));assert.ok(!out.includes('后'));assert.ok(out.includes(END));
});
test('text without a nearby sentence end is cut at the limit with an ellipsis',()=>{
 const out=readingDetail({id:'c',segments:[{t:1,text:'字'.repeat(1000)}]},chapterRow);
 assert.ok(out.includes('字'.repeat(800)+'…</p>'));assert.ok(!out.includes('字'.repeat(801)));assert.ok(out.includes(END));
});
test('notes stay complete because they are the knowledge itself',()=>{
 const out=readingDetail(null,{item:{kind:'note'},source:{title:'记'.repeat(2000)}});
 assert.ok(out.includes('记'.repeat(2000)));assert.ok(!out.includes(END));
});
