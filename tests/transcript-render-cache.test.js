const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function harness(){
 const start=html.indexOf('const transcriptRenderCache=new Map();');
 assert.ok(start>=0,'render cache exists');
 const feed={clientWidth:800,children:[],querySelector:()=>null},wrap={clientWidth:900,clientHeight:700};
 const context=vm.createContext({$:id=>id==='feed'?feed:wrap,getComputedStyle:()=>({fontSize:'16px',lineHeight:'28px',fontFamily:'system-ui'}),
  TRANSCRIPT_LAZY_PAINT_MIN:300,state:'idle',editing:null,transcriptFormatBusy:false});
 vm.runInContext(html.slice(start,html.indexOf('\nasync function loadSession(',start)),context);
 return {context,feed,wrap};
}
function row(){return {matches:()=>false,cloneNode:()=>({classList:{remove(){}},querySelectorAll:()=>[]})};}
function session(id='one'){return {id,segments:Array.from({length:301},(_,t)=>({t,text:'正文'})),notes:[],outline:[],summary:''};}

test('render cache uses current content and layout; playback preferences do not invalidate it',()=>{
 const {context:c,feed,wrap}=harness(),d=session();feed.children=[row()];
 const key=c.transcriptRenderKey(d);c.cacheTranscriptRender(d.id,key);
 assert.equal(c.cachedTranscriptRender(d.id,key).length,1);
 d.last_pos=20;d.play_rate='1.5';assert.equal(c.transcriptRenderKey(d),key);
 d.segments[0].text='编辑';assert.notEqual(c.transcriptRenderKey(d),key);
 d.segments[0].text='正文';d.notes.push({t:0,text:'笔记'});assert.notEqual(c.transcriptRenderKey(d),key);
 d.notes=[];wrap.clientWidth++;assert.notEqual(c.transcriptRenderKey(d),key);
 assert.equal(c.transcriptRenderKey({id:'short',segments:[]}),null);
});

test('cache holds at most two documents and 12000 rows; replacement keeps a fresh snapshot',()=>{
 const {context:c,feed}=harness();feed.children=[row()];
 for(const id of ['one','two','three'])c.cacheTranscriptRender(id,id);
 assert.equal(c.cachedTranscriptRender('one','one'),null);
 assert.equal(c.cachedTranscriptRender('two','changed'),null);
 assert.equal(c.cachedTranscriptRender('three','three').length,1);
 feed.children=Array.from({length:12001},row);c.cacheTranscriptRender('huge','huge');
 assert.equal(c.cachedTranscriptRender('huge','huge'),null);
});


test('active edits and search highlights never enter snapshots',()=>{
 const {context:c,feed}=harness();feed.children=[row()];
 feed.querySelector=()=>({});c.cacheTranscriptRender('editing','key');
 assert.equal(c.cachedTranscriptRender('editing','key'),null);
 feed.querySelector=()=>null;c.cacheTranscriptRender('editing','key');
 assert.equal(c.cachedTranscriptRender('editing','key').length,1);
 c.cacheTranscriptRender('editing','new-key');
 assert.equal(c.cachedTranscriptRender('editing','key'),null);
 assert.equal(c.cachedTranscriptRender('editing','new-key').length,1);
});
