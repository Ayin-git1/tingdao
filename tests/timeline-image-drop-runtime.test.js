const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync('index.html', 'utf8');
function source(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, name);
  return html.slice(start, html.indexOf('\n}', start) + 2);
}
function harness(platform = 'mac') {
  const shown = [], inserted = [], requests = [];
  const elements = {transcriptNoteLayer: {hidden: true}};
  const context = vm.createContext({handleRecordingNativeImageDrag:()=>false,removeTranscriptImageDragGhost(){},moveTranscriptImageDragGhost(){},updateTranscriptImageAutoScroll(){},refreshTranscriptImageDragTarget(){},state:"idle",
    window: {devicePixelRatio: 2}, document: {documentElement: {dataset: {platform}}},
    $: id => elements[id], view: {id: 'test-project', notes: []},
    transcriptNoteNativeDropPaths: [], transcriptNoteSelection: null,
    transcriptNoteImageMime: file => file.name.endsWith('.png') ? 'image/png' : '',
    transcriptNoteRangeAtPoint: () => null,
    transcriptImageDropTarget: (x,y) => x === 800 && y === 400 ? {time: 12, before: null} : null,
    showTranscriptImageDropIndicator: target => shown.push(target.time),
    hideTranscriptImageDropIndicator: () => shown.push('hide'),
    showTranscriptNoteDropIndicator: () => shown.push('editor'),
    hideTranscriptNoteDropIndicator: () => {},
    insertTranscriptNoteNativeFiles: paths => inserted.push(paths),
    insertTranscriptImageFiles: (files,target,native) => inserted.push({files,time:target.time,native}),
    currentDropIntent:null,currentImageDropTarget:null,transcriptDraggedImage:null,imageDropPreviewMedia:null,imageDropPreviewRects:new Map(),
    loadImageDropPreviewMedia:()=>{},endImageDropDrag:()=>{},
    clearImageDropPreview:()=>{},commitImageDrop:(files,target,native)=>inserted.push({files,time:target.time,native}),
    api: async (path,body) => { requests.push({path,body}); return {notes: [{t:body.t,content:body.content}]}; },
    renderTimelineNotes: () => shown.push('render'), refreshHistory: () => {}, toast: () => {},
    transcriptNoteReadNativeFile: async path => ({id:'asset-1',name:path,mime:'image/png',data:'AA==',width:100,height:50}),
    transcriptNoteReadFile: async file => ({id:'asset-1',name:file.name,mime:'image/png',data:'AA==',width:100,height:50}),
  });
  for (const name of ['transcriptNoteNativeEventPayload','transcriptNoteNativeImageMime',
    'transcriptNoteNativeImagePaths','transcriptNoteNativeClientPoint','handleTranscriptNoteNativeDrag'])
    vm.runInContext(source(name), context);
  return {context,shown,inserted,requests,elements};
}
test('macOS Retina native coordinates hit the same CSS insertion point', () => {
  const {context} = harness();
  const point = context.transcriptNoteNativeClientPoint({position:{x:800,y:400}});
  assert.equal(point.x,800); assert.equal(point.y,400);
});
test('Windows physical coordinates are converted to CSS pixels', () => {
  const {context} = harness('windows');
  const point = context.transcriptNoteNativeClientPoint({position:{x:1600,y:800}});
  assert.equal(point.x,800); assert.equal(point.y,400);
});
test('native drag into transcript shows insertion target and drops without an open note editor', () => {
  const {context,shown,inserted} = harness();
  const payload = {paths:['/tmp/test.png'],position:{x:800,y:400}};
  context.handleTranscriptNoteNativeDrag('enter',{payload});
  assert.ok(shown.includes(12), 'transcript placeholder should appear');
  context.handleTranscriptNoteNativeDrag('drop',{payload});
  assert.equal(inserted.length,1); assert.equal(inserted[0].time,12);
  assert.equal(inserted[0].native,true);
});
test('direct transcript insertion saves image assets and updates session notes', async () => {
  const {context,requests,shown} = harness();
  vm.runInContext('async ' + source('insertTranscriptImageFiles'),context);
  await context.insertTranscriptImageFiles(['/tmp/test.png'],{time:12},true);
  assert.equal(requests.length,1);
  assert.equal(requests[0].path,'/api/timeline_note');
  assert.equal(requests[0].body.id,'test-project');
  assert.equal(requests[0].body.t,12);
  assert.equal(requests[0].body.content[0].asset,'asset-1');
  assert.equal(requests[0].body.content[0].position.mode,'flow');
  assert.equal(requests[0].body.content[0].position.x,null);
  assert.equal(requests[0].body.content[0].position.y,null);
  assert.equal(requests[0].body.assets[0].data,'AA==');
  assert.equal(context.view.notes.length,1);
  assert.ok(shown.includes('render'));
});

test('native editor drops retain their insertion range; leaving clears the target', () => {
  const {context,elements,shown,inserted} = harness();
  elements.transcriptNoteLayer.hidden = false;
  const savedRange = {};
  context.transcriptNoteRangeAtPoint = () => ({cloneRange: () => savedRange});
  const payload = {paths:['/tmp/test.png'],position:{x:800,y:400}};
  context.handleTranscriptNoteNativeDrag('enter',{payload});
  assert.ok(shown.includes('editor'));
  context.handleTranscriptNoteNativeDrag('drop',{payload});
  assert.equal(context.transcriptNoteSelection,savedRange);
  assert.equal(inserted[0][0],'/tmp/test.png');
  context.handleTranscriptNoteNativeDrag('leave',{});
  assert.equal(context.transcriptNoteNativeDropPaths.length,0);
});

test('actual transcript hit test selects the gap after the preceding timestamp', () => {
  const {context,elements} = harness();
  const bounds = {left:100,right:900,top:100,bottom:700,width:800};
  const rows = [0,12,30].map((t,i) => ({dataset:{t,rowId:`segment-${i}`},querySelector:()=>({getBoundingClientRect:()=>({left:166,width:734})}),getBoundingClientRect: () => ({top:100+i*100,bottom:200+i*100,height:100})}));
  rows.forEach((row,i)=>row.nextSibling=rows[i+1]||null);
  vm.runInContext(source('resolveImageAsideWidth'),context);
  vm.runInContext(source('resolveImageDropIntent'),context);
  elements.feedwrap = {getBoundingClientRect:()=>bounds,getClientRects:()=>[bounds]};
  elements.feed = {querySelectorAll:()=>rows};
  vm.runInContext(source('transcriptImageDropTarget'),context);
  const target = context.transcriptImageDropTarget(500,280);
  assert.equal(target.time,12); assert.equal(target.before,rows[2]);
  assert.equal(target.x,undefined); assert.equal(target.y,undefined);
  assert.equal(context.transcriptImageDropTarget(50,280),null);
  elements.transcriptNoteLayer.hidden=false;
  assert.equal(context.transcriptImageDropTarget(500,280),null);
});

test('failed image save reports error without creating a phantom note', async () => {
  const {context,shown} = harness();
  const messages=[];
  context.api=async()=>({error:'保存失败'});context.toast=message=>messages.push(message);
  vm.runInContext('async '+source('insertTranscriptImageFiles'),context);
  await context.insertTranscriptImageFiles([{name:'test.png'}],{time:12});
  assert.equal(context.view.notes.length,0);assert.ok(!shown.includes('render'));
  assert.deepEqual(messages,['保存失败']);
});

test('image layout menu pointerdown does not dismiss its note editor', () => {
  const handlers=[];
  const start=html.indexOf("document.addEventListener('pointerdown',e=>{",html.indexOf("$('transcriptNoteDelete').onclick"));
  const listener=html.slice(start,html.indexOf('\n});',start)+4);
  const menuTarget={}, outside={};let closed=0;
  const elements={
    transcriptNoteMenu:{hidden:true,contains:()=>false},
    transcriptNoteLayer:{hidden:false,querySelector:()=>({contains:()=>false})},
    transcriptNoteImageMenu:{contains:target=>target===menuTarget},
  };
  vm.runInNewContext(listener,{document:{addEventListener:(_,fn)=>handlers.push(fn)},
    $:id=>elements[id],closeTranscriptNote:()=>closed++,hideTranscriptNoteMenu:()=>{}});
  handlers[0]({target:menuTarget});assert.equal(closed,0);
  handlers[0]({target:outside});assert.equal(closed,1);
});

test('image insertion range is before its left half and after its right half', () => {
  const {context,elements} = harness();
  const figure={getBoundingClientRect:()=>({left:100,width:100})};
  const holder={nodeType:1,closest:()=>figure};
  elements.transcriptNoteText={contains:()=>true,getBoundingClientRect:()=>({left:0,right:500,top:0,bottom:500})};
  context.Node={ELEMENT_NODE:1};
  context.document.caretRangeFromPoint=()=>({startContainer:holder});
  context.document.createRange=()=>({selectNode:()=>{},collapse(value){this.before=value;}});
  vm.runInContext(source('transcriptNoteRangeAtPoint'),context);
  assert.equal(context.transcriptNoteRangeAtPoint(120,100).before,true);
  assert.equal(context.transcriptNoteRangeAtPoint(180,100).before,false);
});

test('native drag bridge registers all four actual Tauri callbacks', async () => {
  const {context,shown} = harness();
  const callbacks=[],calls=[];
  context.window.__TAURI_INTERNALS__={
    transformCallback:fn=>{callbacks.push(fn);return callbacks.length-1;},
    invoke:async(command,args)=>calls.push({command,args}),
  };
  vm.runInContext(source('registerTranscriptNoteNativeDragBridge'),context);
  context.registerTranscriptNoteNativeDragBridge();
  assert.deepEqual(calls.map(call=>call.args.event),[
    'tauri://drag-enter','tauri://drag-over','tauri://drag-drop','tauri://drag-leave',
  ]);
  assert.ok(calls.every(call=>call.command==='plugin:event|listen'&&call.args.target.label==='main'));
  callbacks[0]({payload:{paths:['/tmp/test.png'],position:{x:800,y:400}}});
  assert.ok(shown.includes(12));
});

test('file-picker image reader decodes dimensions and supplies actual image data to saving', async () => {
  const {context,requests} = harness();
  context.TRANSCRIPT_NOTE_MAX_IMAGE_BYTES=20*1024*1024;
  context.transcriptNoteAssetId=()=> 'decoded-image';
  context.FileReader=class {readAsDataURL(){this.result='data:image/png;base64,aW1hZ2U=';this.onload();}};
  context.Image=class {set src(value){this.naturalWidth=640;this.naturalHeight=480;this.onload();}};
  vm.runInContext(source('transcriptNoteReadFile'),context);
  vm.runInContext('async '+source('insertTranscriptImageFiles'),context);
  await context.insertTranscriptImageFiles([{name:'test.png',size:20}],{time:12});
  assert.equal(requests[0].body.assets[0].data,'aW1hZ2U=');
  assert.equal(requests[0].body.content[0].width,640);
  assert.equal(requests[0].body.content[0].displayWidth,260);
  await assert.rejects(context.transcriptNoteReadFile({name:'test.png',size:21*1024*1024}),/20 MB/);
});

test('saved manuscript images expose their content index and direct interaction seam', () => {
  assert.match(html, /dataset\.noteContentIndex/);
  assert.match(html, /function transcriptMainImageTarget\(/);
  assert.match(html, /transcript-note-image.*contextmenu|contextmenu.*transcript-note-image/s);
  assert.match(html, /transcript-note-image.*pointerdown|pointerdown.*transcript-note-image/s);
});

test('manuscript images render independently of note cards',()=>{
  assert.doesNotMatch(html,/function createTranscriptNoteCard\(/);
  assert.match(html,/function createTranscriptNoteImage\(/);
  assert.match(html,/image-aside-row/);
});

test('flow manuscript images expose resize and persist flow geometry', () => {
  assert.match(html, /transcript-note-image-resize/);
  assert.match(html, /function startTranscriptMainImageResize\(/);
  assert.match(html, /displayWidth/);
  assert.match(html, /function persistTranscriptMainImageResize\(/);
  assert.match(html, /position:\{mode:'flow',x:null,y:null\}/);
  assert.match(html, /data-action="delete"/);
  assert.match(html, /function deleteTranscriptMainImage\(/);
  assert.doesNotMatch(html, /transcriptMainImageMoveState/);
  assert.doesNotMatch(html, /timeline_note_image_move/);
});

test('main image resizing calls the note update path with the selected node', async () => {
  const requests=[],messages=[];
  const context=vm.createContext({handleRecordingNativeImageDrag:()=>false,state:"idle",handleRecordingNativeImageDrag:()=>false,
    view:{id:'project',notes:[{t:10,text:'文字',content:[{type:'text',text:'文字'},
      {type:'image',file:'note-images/a.png',layout:'inline',position:{mode:'flow',x:null,y:null}}]}]},
    api:async(path,body)=>{requests.push({path,body});return {notes:context.view.notes};},
    renderTimelineNotes:()=>{},refreshHistory:()=>{},toast:message=>messages.push(message),
    transcriptNoteUsesFreePosition:layout=>layout==='behind'||layout==='front',
  });
  const start=html.indexOf('function transcriptMainImageTarget(');
  const end=html.indexOf('function setTranscriptNoteImagePosition(',start);
  vm.runInContext(source('resolveTranscriptImageLayout'),context);
  vm.runInContext(html.slice(start,end),context);
  const row={dataset:{noteIndex:'0',noteContentIndex:'1'},classList:{add(){},remove(){}}};
  const target=context.transcriptMainImageTarget(row);
  assert.equal(target.contentIndex,1);
  await context.persistTranscriptMainImageResize(target,320);
  assert.equal(requests[0].path,'/api/timeline_note_update');
  assert.equal(requests[0].body.content[1].displayWidth,320);
  assert.equal(requests[0].body.content[1].position.mode,'flow');
  assert.equal(requests[0].body.content[1].position.x,null);
  assert.equal(requests[0].body.content[1].position.y,null);
  assert.deepEqual(messages,['图片大小已保存']);
});

test('aside drops save equal column width through the existing upload path',async()=>{
 const {context,requests}=harness();vm.runInContext('async '+source('insertTranscriptImageFiles'),context);
 await context.insertTranscriptImageFiles([{name:'test.png'}],{time:12,imageWidth:261,intent:{mode:'aside',side:'right',rowId:'segment-0'}});
 const image=requests[0].body.content[0];assert.equal(image.displayWidth,261);assert.equal(image.layout,'aside-right');assert.equal(image.anchorRowId,'segment-0');
});

test('column resize preserves aside placement in the saved image node',async()=>{
 let saved;const context=vm.createContext({handleRecordingNativeImageDrag:()=>false,state:"idle",handleRecordingNativeImageDrag:()=>false,persistTranscriptMainImageNode:async(target,node)=>{saved=node;return true;}});
 vm.runInContext(source('resolveTranscriptImageLayout'),context);
 vm.runInContext('async '+source('persistTranscriptMainImageResize'),context);
 await context.persistTranscriptMainImageResize({node:{layout:'aside-left',anchorRowId:'segment-0'}},301);
 assert.equal(saved.displayWidth,301);assert.equal(saved.layout,'aside-left');assert.equal(saved.anchorRowId,'segment-0');
});


test('Tauri internal image drag previews and commits without native file paths', () => {
  const {context,shown,inserted} = harness();
  context.transcriptDraggedImage={row:{},node:{asset:'existing-image'}};
  const payload={paths:[],position:{x:800,y:400}};
  context.handleTranscriptNoteNativeDrag('enter',{payload});
  context.handleTranscriptNoteNativeDrag('over',{payload});
  assert.ok(shown.includes(12));
  context.handleTranscriptNoteNativeDrag('drop',{payload});
  assert.equal(inserted.length,1);
  assert.equal(inserted[0].time,12);
  assert.equal(inserted[0].files.length,0);
  assert.equal(context.transcriptNoteNativeDropPaths.length,0);
});

test('Tauri pointer drag keeps the image source until release and saves placement',async()=>{
  const {context,requests}=harness();
  context.window.__TAURI_INTERNALS__={};
  const row={classList:{add(){},remove(){}},setPointerCapture(){},hasPointerCapture:()=>true,
    releasePointerCapture(){},querySelector:()=>({src:'/note-image/a.png',naturalWidth:200,naturalHeight:100})};
  const sourceImage={row,noteIndex:0,contentIndex:0,note:{t:10,text:'',content:[]},
    node:{type:'image',file:'a.png',layout:'inline',width:200,height:100,displayWidth:200}};
  sourceImage.note.content=[sourceImage.node];
  context.transcriptMainImageTarget=()=>sourceImage;
  context.transcriptMainImageContent=(target,node)=>[node];
  context.imageDropMediaVersion=0;context.imageDropMediaLoading=false;
  context.transcriptImagePointerDrag=null;
  context.transcriptImageDropTarget=()=>({time:12,imageWidth:260,intent:{mode:'aside',side:'right',rowId:'segment-3'}});
  for(const name of ['startTranscriptImagePointerDrag','moveTranscriptImagePointerDrag','finishTranscriptImagePointerDrag'])
    vm.runInContext(source(name),context);
  vm.runInContext('async '+source('persistTranscriptMainImageNode'),context);
  vm.runInContext('async '+source('commitImageDrop'),context);
  const event={button:0,pointerId:7,clientX:100,clientY:100,preventDefault(){}};
  context.startTranscriptImagePointerDrag(event,row);
  context.moveTranscriptImagePointerDrag({...event,clientX:800,clientY:400});
  assert.equal(context.transcriptDraggedImage,sourceImage);
  context.finishTranscriptImagePointerDrag({...event,clientX:800,clientY:400});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(requests.length,1);
  assert.equal(requests[0].path,'/api/timeline_note_update');
  assert.equal(requests[0].body.content[0].file,'a.png');
  assert.equal(requests[0].body.content[0].anchorRowId,'segment-3');
  assert.equal(requests[0].body.content[0].layout,'aside-right');
  assert.equal(context.transcriptImagePointerDrag,null);
  assert.equal(context.transcriptImageReleaseClick,true);
});

test('aside images stay above subsequent text and text hover does not reveal divider',()=>{
  assert.match(html,/#feed \.seg\.image-aside-row\{position:relative;z-index:2;\}/);
  assert.doesNotMatch(html,/\.image-aside-row:hover>\.transcript-image-divider/);
  assert.match(html,/\.image-aside-row:has\(>\.transcript-note-image:hover\)>\.transcript-image-divider/);
});

test('aside text keeps every line in its column including long words and focused playback',()=>{
  assert.match(html,/#feed \.seg \.tx\.image-aside-text\{box-sizing:border-box;padding-right:var\(--image-aside-space\);overflow-wrap:anywhere;\}/);
  assert.match(html,/\.tx\.image-aside-text\[data-image-side="left"\]\{padding-left:var\(--image-aside-space\);padding-right:0;\}/);
  assert.doesNotMatch(html,/\.tx\.image-aside-text::before/);
  assert.match(html,/#feed \.seg\.cur \.tx-focus\{/);
});


test('image release click is consumed before paragraph playback; later text clicks pass',()=>{
  const context=vm.createContext({handleRecordingNativeImageDrag:()=>false,state:"idle",handleRecordingNativeImageDrag:()=>false,transcriptImageReleaseClick:true});
  vm.runInContext(source('consumeTranscriptImageClick'),context);
  let prevented=0,stopped=0;
  const textClick={target:{closest:()=>null},preventDefault:()=>prevented++,stopImmediatePropagation:()=>stopped++};
  context.consumeTranscriptImageClick(textClick);
  assert.equal(prevented,1);assert.equal(stopped,1);
  assert.equal(context.transcriptImageReleaseClick,false);
  context.consumeTranscriptImageClick(textClick);
  assert.equal(stopped,1);
  context.consumeTranscriptImageClick({...textClick,target:{closest:()=>({})}});
  assert.equal(stopped,2);
  assert.match(html,/document.addEventListener\('click',consumeTranscriptImageClick,true\)/);
});

test('aside image width above 70 percent becomes inline and persists on resize',async()=>{
 const saved=[];const context=vm.createContext({handleRecordingNativeImageDrag:()=>false,state:"idle",handleRecordingNativeImageDrag:()=>false,persistTranscriptMainImageNode:async(target,node)=>saved.push(node)});
 vm.runInContext(source('resolveTranscriptImageLayout'),context);
 vm.runInContext('async '+source('persistTranscriptMainImageResize'),context);
 for(const side of ['left','right']){
  const node={layout:`aside-${side}`,displayWidth:350,anchorRowId:'segment-2'};
  assert.equal(context.resolveTranscriptImageLayout(node,500).layout,`aside-${side}`);
  assert.equal(context.resolveTranscriptImageLayout({...node,displayWidth:351},500).layout,'inline');
  const target={node,row:{parentElement:{querySelector:()=>({getBoundingClientRect:()=>({width:500})})}}};
  await context.persistTranscriptMainImageResize(target,351);
  assert.equal(saved.at(-1).layout,'inline');assert.equal(saved.at(-1).displayWidth,351);
  assert.equal(saved.at(-1).anchorRowId,'segment-2');
 }
});
