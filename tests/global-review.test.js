const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function model(){const block=html.match(/\/\* GLOBAL_REVIEW_MODEL \*\/([^]*?)\/\* END_GLOBAL_REVIEW_MODEL \*\//);assert.ok(block,'global review model is missing');const ctx=vm.createContext({reviewChapters:()=>[],reviewNotes:s=>s.notes.map(n=>({...n,src:'note:'+n.id,title:n.text})),reviewSource:(item,s)=>s.notes.find(n=>'note:'+n.id===item.src),reviewDayKey:()=> '2026-11-06',reviewToday:()=>new Date('2026-11-06T00:00:00'),reviewDueOffset:i=>i.offset});vm.runInContext(block[1],ctx);return ctx;}
function session(id){return {id,name:id,notes:[{id:'same',text:'笔记',t:1}],review:{items:[{src:'note:same',kind:'note',offset:0,lastOn:null,done:false}],days:{}}};}
test('cross-course rows retain distinct identities, ignore orphan sources and do not mutate stored items',()=>{const m=model(),a=session('a'),b=session('b');a.review.items.push({src:'note:removed'});const rows=m.grRows([a,b]);assert.equal(rows.length,2);assert.notEqual(rows[0].key,rows[1].key);assert.equal(rows[1].session.id,'b');assert.equal(a.review.items.length,2);});
test('due classification excludes today-rated, mastered, future and invalid dates',()=>{const m=model(),s=session('a');const rows=m.grRows([s]);assert.equal(m.grIsDue(rows[0]),true);for(const patch of [{lastOn:'2026-11-06'},{done:true},{offset:1},{offset:NaN}]){const r=m.grRows([{...s,review:{items:[{...s.review.items[0],...patch}]}}])[0];assert.equal(m.grIsDue(r),false);}});
test('knowledge filtering is read-only and combines course, kind and search',()=>{const m=model(),s=session('a'),rows=m.grRows([s,session('b')]);assert.equal(m.grFilter(rows,'a','note','笔记',false).length,1);assert.equal(m.grFilter(rows,'a','chap','',false).length,0);assert.equal(m.grFilter(rows,'','all','找不到',false).length,0);assert.equal(s.review.items[0].lastOn,null);});
function commitHarness(fail=false){
 const row={key:'["a","note:same"]',session:{id:'a',review:{items:[{src:'note:same',lastOn:null,done:false,offset:0}],days:{}}},item:null};row.item=row.session.review.items[0];
 const events=[];const ctx=vm.createContext({gr:{busy:false,tab:'focus',sessions:[row.session]},grActive:()=>row,JSON,reviewDayKey:()=> '2026-11-06',reviewToday:()=>new Date(),reviewIsTodaySafe:i=>i.lastOn==='2026-11-06',grIsDue:r=>!r.item.lastOn,reviewSource:()=>({}),reviewApply:(item,g)=>{item.lastOn='2026-11-06';item.lastG=g;},grRender:()=>events.push('render'),grSave:async(s,next)=>{events.push('save');if(fail)throw Error('disk full');s.review=next;},grDeckRows:()=>[],grCelebrate:async()=>events.push('celebrate'),grMessage:t=>events.push(t),REVIEW_GL:{good:'记得'}});
 const source=html.slice(html.indexOf('async function grCommit(entries){'),html.indexOf('async function grUndo(){'));
 vm.runInContext(source,ctx);return {ctx,row,events};
}
test('a failed cross-course write leaves original progress and current card unchanged',async()=>{const {ctx,row,events}=commitHarness(true);const before=JSON.stringify(row.session.review);await ctx.grCommit([{src:'note:same',g:'good'}]);assert.equal(JSON.stringify(row.session.review),before);assert.equal(ctx.gr.tab,'focus');assert.equal(ctx.gr.busy,false);assert.ok(!events.includes('celebrate'));});
test('completion is shown only after a successful source save',async()=>{const {ctx,row,events}=commitHarness();await ctx.grCommit([{src:'note:same',g:'good'}]);assert.equal(row.session.review.items[0].lastOn,'2026-11-06');assert.equal(ctx.gr.tab,'complete');assert.ok(events.indexOf('save')<events.indexOf('celebrate'));assert.equal(row.session.review.days['2026-11-06'].done,1);});
test('later-source filtering does not pass an array index as the course context',()=>{assert.ok(!html.includes('.filter(reviewSource)'), 'source resolution has an optional course parameter, so array callbacks must wrap it');});
test('another write to the same course invalidates an older undo snapshot',()=>{const before={items:[{src:'a',lastG:'good'}],days:{}},next={items:[{src:'a',lastG:'good'},{src:'b',lastG:'easy'}],days:{}};const c=vm.createContext({gr:{sessions:[{id:'course',review:before}],undo:{sid:'course',after:JSON.stringify(before)}},view:null,reviewSid:null,grRows:()=>[],grCount(){}});const source=html.slice(html.indexOf('function grSyncSession(sid,data){'),html.indexOf('async function grReload(){'));vm.runInContext(source,c);c.grSyncSession('course',next);assert.equal(c.gr.undo,null);assert.equal(c.gr.sessions[0].review.items[1].lastG,'easy');});
test('a global write invalidates the local course undo before syncing its newer progress',()=>{const old={items:[{src:'a',lastG:'good'}],days:{}},next={items:[{src:'a',lastG:'good'},{src:'b',lastG:'easy'}],days:{}};const c=vm.createContext({gr:{sessions:[],undo:null},view:{id:'course'},reviewSid:'course',reviewData:old,reviewUndo:'older local snapshot',grRows:()=>[],grCount(){}});const source=html.slice(html.indexOf('function grSyncSession(sid,data){'),html.indexOf('async function grReload(){'));vm.runInContext(source,c);c.grSyncSession('course',next);assert.equal(c.reviewUndo,null);assert.equal(c.reviewData.items[1].lastG,'easy');});
test('a thousand-course queue groups linked notes only under their own course chapters',()=>{const m=model();m.reviewChapters=s=>s.outline;const sessions=Array.from({length:1000},(_,i)=>({id:'course-'+i,name:'课件'+i,outline:[{src:'ch:0',kind:'chap',t:0,end:600,title:'章节'}],notes:Array.from({length:30},(_,j)=>({id:'n'+j,text:'知识'+j,t:j+1})),review:{items:[{src:'ch:0',kind:'chap',offset:0},...Array.from({length:30},(_,j)=>({src:'note:n'+j,kind:'note',offset:0}))],days:{}}}));const started=performance.now();const rows=m.grRows(sessions);m.grAll=()=>rows;m.gr={course:''};vm.runInContext(html.slice(html.indexOf('function grDeckRows(){'),html.indexOf('function grActive(){')),m);const deck=m.grDeckRows();assert.equal(rows.length,31000);assert.equal(deck.length,1000);assert.equal(new Set(deck.map(r=>r.session.id)).size,1000);console.log('1000 courses / 31000 items model+queue:',Math.round(performance.now()-started),'ms');});
test('knowledge fuzzy search matches split keywords and noncontiguous text without changing notes',()=>{const m=model(),s=session('tarot');s.name='塔罗基础';s.notes[0].text='愚者与旅程起点';const rows=m.grRows([s]);assert.equal(m.grFilter(rows,'','all','塔罗 起点',false).length,1);assert.equal(m.grFilter(rows,'','all','愚旅起',false).length,1);assert.equal(m.grFilter(rows,'','all','月亮水星',false).length,0);assert.equal(s.notes[0].text,'愚者与旅程起点');});
test('search suggestions include unopened manuscript names and locate matched note content',()=>{const m=model(),s=session('tarot');s.name='塔罗基础';s.notes[0].text='自己绝对不愿意做的事情';const rows=m.grRows([s]);const hits=m.grSuggestions(rows,[{id:'outside',name:'未加入复习的个人定位文稿'},{id:'archived',name:'个人定位归档',archived:true}],'个人 定位');assert.equal(hits[0].sid,'outside');assert.equal(hits[0].kind,'course');assert.ok(!hits.some(h=>h.sid==='archived'));const notes=m.grSuggestions(rows,[],'不愿意');assert.equal(notes[0].key,rows[0].key);assert.equal(notes[0].sid,'tarot');});
test('full-screen review slides in from the right and keeps the page beneath it until covered',()=>{
 assert.match(html,/#globalReviewPanel\{[^}]*transform:translateX\(100%\)/);
 assert.match(html,/#globalReviewPanel\.open\{transform:none;transition:transform \.48s cubic-bezier/);
 assert.match(html,/body\.global-review-open:not\(\.global-review-moving\) :is\(\.sidebar/);
 assert.ok(html.includes("document.body.classList.toggle('global-review-open',open);grSlide(open);"));
});
test('body motion never transforms the fixed pagination bar',()=>{
 for(const rule of html.match(/#grBody\[data-slide="(?:next|prev|fade)"\][^{]*\{/g))assert.ok(rule.includes(':not(.gr-pagination)'),rule);
});
test('background refresh keeps loaded content on screen instead of the loading state',()=>{
 assert.ok(html.includes(":!gr.loaded?'<div class=\"gr-empty\" role=\"status\">"));
 assert.ok(html.includes('if(gr.open&&(retrying||!gr.loaded))grRender();'));
});
test('re-entering review starts at the top so the fixed pagination bar stays anchored during the slide',()=>{
 assert.ok(html.includes("panel.hidden=false;panel.scrollTop=0;panel.offsetWidth;panel.classList.add('open');"));
 assert.match(html,/body\.global-review-moving #globalReviewPanel\{overflow:hidden\}/);
});

function knowledgeLayoutHarness(count){
 const rows=Array.from({length:count},(_,i)=>({key:'row-'+i,session:{id:'course',name:'课程'},item:{kind:'note'},source:{t:i,title:'知识'+i}}));
 const c=vm.createContext({gr:{page:0,selected:'',sessions:[],course:'',kind:'all',search:'',weak:false},grFilter:r=>r,grAll:()=>rows,esc:String,grIsDue:()=>false,reviewIsTodaySafe:()=>true,fmt:String,grDetailHtml:()=>'<p>完整知识正文</p>',grNoteTitle:r=>r.source.title,grNoteSummary:()=>'',grSnippet:String});
 vm.runInContext(html.slice(html.includes('function grReadingHtml(')?html.indexOf('function grReadingHtml('):html.indexOf('function grKnowledge(){'),html.indexOf('function grTurnPage(delta){')),c);
 return c.grKnowledge();
}
test('a lone knowledge item uses a single reading layout while multiple items retain browse actions',()=>{
 const single=knowledgeLayoutHarness(1),multiple=knowledgeLayoutHarness(3);
 assert.match(single,/gr-knowledge-layout is-single/);
 assert.ok(single.includes('完整知识正文'));
 assert.ok(single.includes('data-gr-jump="row-0"'));
 assert.doesNotMatch(multiple,/gr-knowledge-layout is-single/);
 assert.ok(multiple.includes('data-gr-select="row-1"'));
});
test('course directory names appear once and course review actions stay scoped',()=>{
 const s={id:'course-id',name:'独立课程',review:{items:[{}]}};
 const c=vm.createContext({gr:{sessions:[s],courseLimit:24},grAll:()=>[{session:s}],grIsDue:()=>true,grTodayRows:()=>[],reviewToday:()=>new Date(),reviewMd:()=>'',grHeroCount:()=>'',grHeroStatus:()=>'',grWeek:()=>'',esc:String});
 vm.runInContext(html.slice(html.indexOf('function grOverview(){'),html.indexOf('function grFocus(){')),c);
 const rendered=c.grOverview();
 assert.equal(rendered.split('独立课程').length-1,1);
 assert.ok(rendered.includes('data-gr-start="course-id"'));
 assert.ok(rendered.replace(/<[^>]*>/g,'').includes('1 条待复习'));
});
test('overview hero offers entering review only while something is due today',()=>{
 const s={id:'c',name:'c',review:{items:[{}]}};
 const hero=due=>{const c=vm.createContext({gr:{sessions:[s],courseLimit:24},grAll:()=>[{session:s}],grIsDue:()=>due,grTodayRows:()=>[],reviewToday:()=>new Date(),reviewMd:()=>'',grHeroCount:()=>'',grHeroStatus:()=>'',grWeek:()=>'',esc:String});
  vm.runInContext(html.slice(html.indexOf('function grOverview(){'),html.indexOf('function grFocus(){')),c);return c.grOverview().match(/<button class="gr-hero-link"[^>]*>([^<]*)/);};
 const due=hero(true),idle=hero(false);
 assert.match(due[0],/data-gr="start"/);assert.equal(due[1].trim(),'进入复习');
 assert.match(idle[0],/data-gr="knowledge"/);assert.equal(idle[1].trim(),'浏览知识');
});
test('finished overview greets in English with a damped reel that stops for reduced motion and closed panels',()=>{
 assert.ok(!html.includes('今天的安排，已经完成'));
 assert.ok(html.includes('That’s a wrap'));
 const spring=model();vm.runInContext(html.slice(html.indexOf('const GR_CHEER'+'S='),html.indexOf('function grCheerPick(')),spring);
 const curve=vm.runInContext('GR_CHEER_SPRING',spring);
 assert.equal(curve[0],0);assert.ok(Math.abs(curve.at(-1)-1)<.001);
 assert.ok(Math.max(...curve)>1&&Math.max(...curve)<1.08,'the reel overshoots a little, then settles');
 const loop=html.slice(html.indexOf('function grCheerLoop(){'),html.indexOf('function grOverview(){'));
 assert.ok(loop.includes("prefers-reduced-motion:reduce"));
 assert.ok(loop.includes('if(!gr.open||!reel.isConnected)return;'));
 assert.ok(html.includes('gr.open=open;gr.epoch++;gr.cheerEntered=false;'),'reopening the panel plays the entrance again');
 assert.ok(loop.includes('if(!reel){gr.cheerEntered=false;return;}'),'returning from another tab plays the entrance again');
 assert.ok(html.slice(html.indexOf('function grCheerGlitch('),html.indexOf('function grCheerLoop(){')).includes('gr.cheerEntered=true;'),'the entrance counts from the moment it starts, so a background refresh cannot repeat it');
 assert.ok(!html.slice(html.indexOf('function grCheerRoll('),html.indexOf('function grCheerGlitch(')).includes('gr.cheerEntered'),'the idle roll never marks the entrance as played');
 const land=vm.runInContext('GR_CHEER_JUMP',spring);
 assert.ok(Math.max(...land)>1.1&&Math.abs(land.at(-1)-1)<.01,'the entrance lands with a visible bounce');
});

test('knowledge browsing retains every card and its selected item in the stream',()=>{
 const markup=knowledgeLayoutHarness(13);
 assert.equal((markup.match(/data-gr-select=/g)||[]).length,13);
 assert.ok(markup.includes('data-gr-select="row-0"'));
 assert.ok(markup.includes('data-gr-select="row-12"'));
});
test('global review messages use the app toast and keep only the reload action inline',()=>{const shown=[];const c=vm.createContext({toast:t=>shown.push(t),$:()=>null});vm.runInContext(html.match(/function grMessage[^\n]*/)[0],c);c.grMessage('已撤销上一次评分');assert.deepEqual(shown,['已撤销上一次评分']);});
test('mastering mid-queue plays the same delayed sound as the review card, only after saving',async()=>{const {ctx,row,events}=commitHarness();ctx.grDeckRows=()=>[row];ctx.reviewApply=item=>{item.lastOn='2026-11-06';return true;};ctx.setTimeout=(f,ms)=>{events.push('timer:'+ms);f();};ctx.reviewPlay=k=>events.push(k);await ctx.grCommit([{src:'note:same',g:'easy'}]);assert.ok(events.indexOf('save')<events.indexOf('master'));assert.ok(events.includes('timer:160'));});
test('the last card tells the celebration whether something was mastered',async()=>{const {ctx}=commitHarness();let arg;ctx.reviewApply=()=>true;ctx.grCelebrate=async m=>{arg=m;};await ctx.grCommit([{src:'note:same',g:'easy'}]);assert.equal(arg,true);});
test('celebration sounds are not tied to animation completion',()=>{const body=html.slice(html.indexOf('async function grCelebrate('),html.indexOf('function grKindOpen('));assert.ok(!body.includes('clearTimeout'));assert.ok(body.includes("reviewPlay(mastered?'master':'bell')"));});
test('see-all action only appears when another course has due items',()=>{const body=html.slice(html.indexOf('function grFocus(){'),html.indexOf('function grNoteTitle('));const render=(course,rows,today)=>{const c=vm.createContext({gr:{course},grActive:()=>undefined,grAll:()=>rows,grIsDue:r=>r.due,grTodayRows:()=>today});vm.runInContext(body,c);return c.grFocus();};assert.match(render('a',[{due:true}],[]),/data-gr="all-start"/);assert.doesNotMatch(render('',[],[{}]),/all-start/);assert.match(render('',[],[{}]),/data-gr="complete"/);assert.doesNotMatch(render('',[],[]),/data-gr="complete"/);});
test('every global review tab scrolls inside the content area under a fixed header',()=>{assert.ok(html.includes('<div class="gr-shell gr-scroll-body">'));assert.ok(!html.includes('calc(100dvh - 300px)'));});
test('narrow windows keep the current-course column instead of hiding it',()=>{assert.ok(!html.includes('.gr-focus-layout>aside:first-child{display:none}'));assert.ok(html.includes('grid-template-columns:minmax(120px,1fr) minmax(0,550px) minmax(120px,1fr)'));});
test('short windows give height to the card by collapsing the repeated heading',()=>{assert.match(html,/\.gr-scroll-body:has\(#grBody>\.gr-focus-layout\) \.gr-heading\{height:0;opacity:0/);assert.ok(html.includes('.gr-deck{min-height:340px;max-height:none}'));});
test('the heading collapse and return share an animated path for tab switches and window resizes',()=>{assert.match(html,/\.gr-heading\{[^}]*transition:height \.36s/);const c=vm.createContext({getComputedStyle:e=>e.css});vm.runInContext(html.slice(html.indexOf('function grChrome(panel){'),html.indexOf('/* 整块 innerHTML 重绘后')),c);const calls=[];const el=css=>({css,animate:a=>calls.push(a)});const panel=css=>({querySelector:s=>s==='.gr-header'?el({paddingTop:css[0]}):s==='.gr-heading'?el({height:css[1]}):el({marginTop:css[2]})});c.grChromeMotion(panel(['52px','0px','0px']),{pad:'65px',height:'41px',gap:'24px'});assert.equal(calls.length,4);calls.length=0;c.grChromeMotion(panel(['65px','41px','24px']),{pad:'65px',height:'41px',gap:'24px'});assert.equal(calls.length,0);});
test('knowledge entry motion keeps the reading card above the pager fade',()=>{
 for(const kind of ['next','prev','fade']){
  const rule=html.match(new RegExp(`#grBody\\[data-slide="${kind}"\\][^{]*\\{`))[0];
  assert.ok(rule.includes(':not(.gr-knowledge-layout)'),'the layout must not become one stacking context while animating');
  assert.ok(rule.includes('.gr-knowledge-layout>*'),'its children animate separately so each keeps its own stacking level');
 }
});
