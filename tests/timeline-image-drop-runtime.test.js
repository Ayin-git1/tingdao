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
  const context = vm.createContext({
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
  const rows = [0,12,30].map((t,i) => ({dataset:{t},getBoundingClientRect: () => ({top:100+i*100,height:100})}));
  elements.feedwrap = {getBoundingClientRect:()=>bounds,getClientRects:()=>[bounds]};
  elements.feed = {querySelectorAll:()=>rows};
  vm.runInContext(source('transcriptImageDropTarget'),context);
  const target = context.transcriptImageDropTarget(500,280);
  assert.equal(target.time,12); assert.equal(target.before,rows[2]);
  assert.equal(context.transcriptImageDropTarget(50,280),null);
  elements.transcriptNoteLayer.hidden=false;
  assert.equal(context.transcriptImageDropTarget(500,280),null);
});

test('empty transcript still has a visible positive-width placeholder', () => {
  const {context,elements} = harness();
  const classes = new Set(), attrs = {};
  const indicator = {style:{},classList:{add:name=>classes.add(name)},setAttribute:(name,value)=>attrs[name]=value};
  elements.transcriptImageDropIndicator=indicator;
  elements.feedwrap={getBoundingClientRect:()=>({left:100,top:100,bottom:700,width:800})};
  elements.feed={getBoundingClientRect:()=>({left:0,top:0,bottom:0,width:0})};
  vm.runInContext(source('showTranscriptImageDropIndicator'),context);
  context.showTranscriptImageDropIndicator({before:null});
  assert.equal(indicator.style.width,'800px');
  assert.ok(classes.has('show')); assert.equal(attrs['aria-hidden'],'false');
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
  assert.match(html, /note-image.*contextmenu|contextmenu.*note-image/s);
  assert.match(html, /note-image.*pointerdown|pointerdown.*note-image/s);
});

test('manuscript images render as independent canvas objects instead of timestamp rows', () => {
  assert.match(html, /id="transcriptImageCanvas"/);
  assert.match(html, /function createTranscriptCanvasImage\(/);
  assert.doesNotMatch(html, /div\.className='seg note-image'/);
  assert.doesNotMatch(html, /createNoteImageDom\(/);
});

test('independent manuscript images expose resize and persisted canvas geometry', () => {
  assert.match(html, /transcript-canvas-image-resize/);
  assert.match(html, /function startTranscriptMainImageResize\(/);
  assert.match(html, /displayWidth/);
  assert.match(html, /position:\{mode:'free',x:/);
  assert.match(html, /data-action="delete"/);
  assert.match(html, /function deleteTranscriptMainImage\(/);
});

test('manuscript image movement has a dedicated persisted API path', () => {
  assert.match(html, /function persistTranscriptMainImageMove\(/);
  assert.match(html, /api\('\/api\/timeline_note_image_move'/);
  assert.match(html, /function persistTranscriptMainImagePosition\(/);
});

test('main image layout and movement call the real persistence paths with the selected node', async () => {
  const requests=[],messages=[];
  const context=vm.createContext({
    view:{id:'project',notes:[{t:10,text:'文字',content:[{type:'text',text:'文字'},
      {type:'image',file:'note-images/a.png',layout:'inline',position:{mode:'flow',x:null,y:null}}]}]},
    api:async(path,body)=>{requests.push({path,body});return {notes:context.view.notes};},
    renderTimelineNotes:()=>{},refreshHistory:()=>{},toast:message=>messages.push(message),
    transcriptNoteUsesFreePosition:layout=>layout==='behind'||layout==='front',
  });
  const start=html.indexOf('function transcriptMainImageTarget(');
  const end=html.indexOf('function startTranscriptMainImageResize(',start);
  vm.runInContext(html.slice(start,end),context);
  const row={dataset:{noteIndex:'0',noteContentIndex:'1'},classList:{add(){},remove(){}}};
  const target=context.transcriptMainImageTarget(row);
  assert.equal(target.contentIndex,1);
  await context.setTranscriptMainImageLayout(target,'front');
  assert.equal(requests[0].path,'/api/timeline_note_update');
  assert.equal(requests[0].body.content[1].layout,'front');
  assert.equal(requests[0].body.content[1].position.mode,'free');
  await context.persistTranscriptMainImageMove(target,140,260,320);
  assert.equal(requests[1].path,'/api/timeline_note_image_move');
  assert.equal(requests[1].body.note_index,0);
  assert.equal(requests[1].body.content_index,1);
  assert.equal(requests[1].body.x,140);
  assert.equal(requests[1].body.y,260);
  assert.equal(requests[1].body.display_width,320);
  assert.deepEqual(messages,['图片排版已保存','图片位置已保存']);
});
