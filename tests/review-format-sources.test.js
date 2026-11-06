const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function model(){const ctx=vm.createContext({view:null});vm.runInContext(html.slice(html.indexOf('function reviewNotes('),html.indexOf('function reviewChapterOf(')),ctx);return ctx;}
const segment={t:12,text:'划线文字背景文字普通文字',formats:[{start:0,end:4,style:{underline:true}},{start:4,end:6,style:{background:'#ffff00'}},{start:6,end:8,style:{background:'#ffff00',bold:true}},{start:8,end:12,style:{color:'#ff0000'}}]};
test('review candidates include underline and background text once, with stable source and original time',()=>{
 const m=model(),s={notes:[{id:'n',t:1,text:'原有笔记'}],segments:[segment]};
 const notes=m.reviewNotes(s);assert.equal(notes.length,2);assert.equal(notes[0].src,'note:n');assert.equal(notes[1].title,'划线文字背景文字');assert.equal(notes[1].t,12);assert.ok(notes[1].src);assert.equal(m.reviewSource({src:notes[1].src,kind:'note'},s).title,notes[1].title);
 const projected={reviewSegments:[segment]};assert.equal(m.reviewNotes(projected)[0].src,notes[1].src);
 assert.equal(m.reviewNotes({...s,segments:[{...segment,formats:[]}]}).length,1);
});
test('separate excerpts remain separate and blank or bold-only formatting is excluded',()=>{
 const m=model();const notes=m.reviewNotes({segments:[{t:4,text:'甲乙丙丁 戊',formats:[{start:0,end:1,style:{underline:true}},{start:2,end:3,style:{background:'#ffff00'}},{start:4,end:5,style:{underline:true}},{start:5,end:6,style:{bold:true}}]}]});
 assert.deepEqual(Array.from(notes,n=>n.title),['甲','丙']);assert.notEqual(notes[0].src,notes[1].src);
});
test('formatted excerpts can be selected and saved without creating timeline note IDs',async()=>{
 const m=model(),elements={reviewAddGo:{},reviewPick:{},reviewAddTabs:{querySelectorAll:()=>[]}};
 Object.assign(m,{view:{id:'course',segments:[segment]},reviewChapters:()=>[],reviewSid:'course',reviewAddTab:'note',reviewSel:new Set(),reviewData:{items:[]},$:id=>elements[id],reviewSlide(){},reviewEsc:String,fmt:String,reviewOnBoard:src=>m.reviewData.items.some(i=>i.src===src),reviewNewItem:(src,kind)=>({src,kind}),reviewPlay(){},reviewGo(){},reviewRenderAll(){},reviewSave:async()=>{},api:async()=>{throw Error('excerpt must not request note IDs');}});
 vm.runInContext(html.slice(html.indexOf('function reviewRenderPick('),html.indexOf('function reviewRemove(')),m);
 m.reviewRenderPick();const src=m.reviewNotes(m.view)[0].src;assert.ok(elements.reviewPick.innerHTML.includes(`data-key="${src}"`));m.reviewSel.add(src);await m.reviewAddSelected();assert.equal(m.reviewData.items[0].src,src);assert.equal(m.reviewData.items[0].kind,'note');m.reviewRenderPick();assert.ok(elements.reviewPick.innerHTML.includes('已加入'));
});
test('global review resolves formatted excerpts after reloading the compact course index',()=>{
 const m=model();Object.assign(m,{reviewChapters:()=>[],reviewDueOffset:()=>0});vm.runInContext(html.match(/\/\* GLOBAL_REVIEW_MODEL \*\/([^]*?)\/\* END_GLOBAL_REVIEW_MODEL \*\//)[1],m);
 const src=m.reviewNotes({segments:[segment]})[0].src;const sessions=JSON.parse(JSON.stringify([{id:'course',reviewSegments:[segment],review:{items:[{src,kind:'note'}]}}]));const rows=m.grRows(sessions);assert.equal(rows.length,1);assert.equal(rows[0].source.title,'划线文字背景文字');assert.equal(rows[0].source.segmentTime,12);
});
