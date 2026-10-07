const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const html=fs.readFileSync('index.html','utf8');
function source(name){const start=html.indexOf(`function ${name}(`);return html.slice(start,html.indexOf('\n}',start)+2);}
test('opening a note attaches the editor directly after its selected row and focuses it',()=>{
 const elements=new Map();let anchorChild=null,focused=false;
 const card={classList:{remove(){},add(){}},addEventListener(){},offsetWidth:100};
 const layer={style:{removeProperty(){}},querySelector:()=>card,hidden:true};
 elements.set('transcriptNoteLayer',layer);
 elements.set('transcriptNoteText',{focus(){focused=true;}});
 const context=vm.createContext({view:{id:'session',duration:60,notes:[]},
  $:id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id);},
  transcriptNoteTargetRow:{isConnected:true,after(child){anchorChild=child;}},
  transcriptNoteCloseEnd:null,fmt:t=>'00:'+String(t).padStart(2,'0'),
  renderTranscriptNoteContent(){},hideTranscriptNoteMenu(){},fitTranscriptNoteLayer(){},refreshTranscriptImageAsideFlow(){},requestAnimationFrame(){}});
 vm.runInContext(source('openTranscriptNote')+'\nopenTranscriptNote(12);',context);
 assert.equal(anchorChild,layer);assert.equal(layer.hidden,false);assert.equal(focused,true);
 assert.equal(elements.get('transcriptNoteTime').value,'00:12');
 assert.equal(elements.get('transcriptNoteSave').textContent,'确认');
});
test('editor exposes only confirmation and cancellation buttons',()=>{
 const editor=html.slice(html.indexOf('<div class="tn-layer"'),html.indexOf('<div class="modal"',html.indexOf('<div class="tn-layer"')));
 assert.deepEqual([...editor.matchAll(/<button[^>]*id="([^"]+)"/g)].map(m=>m[1]),['transcriptNoteSave','transcriptNoteCancel']);
 assert.match(html,/#feed \.seg\.note\{background:transparent;border:0;display:grid;grid-template-columns:56px minmax\(0,1fr\)/);
 assert.match(html,/#feed \.seg\.note \.ts\{color:var\(--noteink\);background:var\(--note\);border-radius:var\(--radius-4\)/);
});
function deleteHandler(){
 const start=html.indexOf("$('transcriptNoteDelete').onclick=async()=>{");
 return html.slice(start,html.indexOf('\n};',start)+3);
}
for(const hasImages of [false,true])test(`delete action persists removal without a browser confirmation dialog (images=${hasImages})`,async()=>{
 const button={},calls=[],note={t:12,text:'note',content:hasImages?[{type:'text',text:'note'},{type:'image',file:'a.png'}]:[]};
 let rendered=0,hidden=0;
 const context=vm.createContext({$:()=>button,view:{id:'session',notes:[note]},transcriptNoteTargetIndex:0,
  confirm:()=>false,api:async(path,body)=>{calls.push({path,body});return {notes:hasImages?[{...note,text:'',content:[note.content[1]]}]:[]};},
  hideTranscriptNoteMenu(){hidden++;},renderTimelineNotes(){rendered++;},refreshHistory(){},toast(){}});
 vm.runInContext(deleteHandler(),context);await button.onclick();
 assert.equal(calls.length,1);
 assert.equal(calls[0].path,hasImages?'/api/timeline_note_update':'/api/timeline_note_delete');
 assert.equal(calls[0].body.expected_text,'note');assert.equal(rendered,1);assert.equal(hidden,1);
 if(hasImages){assert.equal(calls[0].body.text,'');assert.equal(calls[0].body.content.length,1);assert.equal(calls[0].body.content[0].file,'a.png');}
 else assert.equal(context.view.notes.length,0);
});
