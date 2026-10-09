const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
function body(name){const match=html.match(new RegExp(`function ${name}\\([^)]*\\)\\{[\\s\\S]*?\\n\\}`));assert.ok(match,`${name} exists`);return match[0];}
test('selected manuscript text cancels queued playback including delayed selection',()=>{
 let pending,seeks=0,selected=false;
 const ctx={clearTimeout:()=>pending=null,setTimeout:fn=>(pending=fn,1),player:{getAttribute:()=> 'audio'},seekTo:()=>seeks++,window:{getSelection:()=>({isCollapsed:!selected,rangeCount:1})}};
 vm.createContext(ctx);vm.runInContext('let segmentPlaybackTimer=null;'+body('queueSegmentPlayback'),ctx);
 const row={dataset:{},isConnected:true},event={detail:1,target:{closest:()=>null}};
 selected=true;ctx.queueSegmentPlayback(event,row,10);assert.equal(pending,null);
 selected=false;ctx.queueSegmentPlayback(event,row,10);selected=true;pending();assert.equal(seeks,0);
 selected=false;ctx.queueSegmentPlayback(event,row,10);pending();assert.equal(seeks,1);
});
test('overlapping schemes replace only selected characters and retain outside format',()=>{
 const ctx={};vm.createContext(ctx);vm.runInContext(body('mergeTranscriptFormats'),ctx);
 const out=ctx.mergeTranscriptFormats([{start:0,end:5,style:{bold:true}}],2,4,{color:'#df7930'},6);
 assert.deepEqual(JSON.parse(JSON.stringify(out)),[{start:0,end:2,style:{bold:true}},{start:2,end:4,style:{color:'#df7930'}},{start:4,end:5,style:{bold:true}}]);
 assert.deepEqual(JSON.parse(JSON.stringify(ctx.mergeTranscriptFormats(out,1,5,{},6))),[{start:0,end:1,style:{bold:true}}]);
});
test('view reset preserves the reusable note editor outside the cleared feed',()=>{
 let moved=false;const card={classList:{remove(){}}},layer={hidden:false,querySelector:()=>card};
 const ctx={$:id=>id==='transcriptNoteLayer'?layer:{disabled:true},document:{body:{appendChild:node=>{assert.equal(node,layer);moved=true;}}},hideTranscriptFormatTools(){}};
 vm.createContext(ctx);vm.runInContext('let transcriptNoteCloseEnd=null;'+body('resetTranscriptNoteLayer'),ctx);
 ctx.resetTranscriptNoteLayer();assert.equal(layer.hidden,true);assert.equal(moved,true);
});
test('toolbar interaction with unchanged selection retains the custom draft',()=>{
 const row={},selection={sid:'s',parts:[{row,start:1,end:5}],rect:{},range:{}};
 const ctx={captureTranscriptFormatSelection:()=>selection,clearTimeout(){},renderTranscriptFormatToolbar(){},positionTranscriptFormatTools(){},$:()=>({hidden:false})};
 vm.createContext(ctx);ctx.selection=selection;
 vm.runInContext('let segmentPlaybackTimer=null;let transcriptFormatSelection=selection;let transcriptFormatDraft={color:"#cc4477"};let transcriptFormatPrefs={last:{bold:true}};let transcriptFormatBusy=false;'+body('refreshTranscriptFormatSelection'),ctx);
 ctx.refreshTranscriptFormatSelection();assert.equal(vm.runInContext('transcriptFormatDraft.color',ctx),'#cc4477');
});
test('highlight keeps heading opacity with a slightly taller square strip',()=>{
 const ctx={};vm.createContext(ctx);
 const highlight=body('transcriptMarkerInk')+body('transcriptHighlightColor');
 vm.runInContext(highlight+body('transcriptFormatCSS'),ctx);
 const css=ctx.transcriptFormatCSS({background:'#eaf1ec'});
 assert.match(css,/rgba\(78,153,116,0\.28\)/);
 assert.match(css,/background-size:100% 1\.2em/);
 assert.match(css,/border-radius:0/);
 assert.doesNotMatch(css,/padding|box-shadow|background-color:#/);
});

test('explicit text color keeps its original value without theme variables',()=>{
 const ctx={};vm.createContext(ctx);vm.runInContext(body('transcriptMarkerInk')+body('transcriptHighlightColor')+body('transcriptFormatCSS'),ctx);
 const css=ctx.transcriptFormatCSS({color:'#c0594e'});
 assert.equal(css,'color:#df4b43;-webkit-text-fill-color:#df4b43;');
});
test('bold toggle preserves color and underline while toggling off',()=>{
 const ctx={};vm.createContext(ctx);vm.runInContext(body('mergeTranscriptFormats'),ctx);
 const formats=[{start:0,end:4,style:{color:'#c0594e',underline:true,bold:true}}];
 const out=ctx.mergeTranscriptFormats(formats,1,3,{},4,'bold',false);
 assert.deepEqual(JSON.parse(JSON.stringify(out)),[{start:0,end:1,style:formats[0].style},{start:1,end:3,style:{color:'#c0594e',underline:true}},{start:3,end:4,style:formats[0].style}]);
});
test('marker stays transparent and restores original palette colors',()=>{
 const ctx={};vm.createContext(ctx);vm.runInContext(body('transcriptMarkerInk')+body('transcriptHighlightColor')+body('transcriptFormatCSS'),ctx);
 assert.equal(ctx.transcriptMarkerInk('#c0594e'),'#df4b43');
 assert.equal(ctx.transcriptMarkerInk('#123456'),'#123456');
 const css=ctx.transcriptFormatCSS({background:'#f8f3de'});
 assert.doesNotMatch(css,/linear-gradient\(#fff|text-fill-color/);
 assert.match(css,/rgba\(212,154,39,0\.28\)/);
});
test('palette opening never moves its anchored toolbar',()=>{
 const bar={offsetHeight:42},palette={hidden:false,scrollHeight:320,offsetHeight:320,style:{setProperty(){}},dataset:{}};
 const tools={offsetWidth:248,style:{left:'100px',top:'150px'},querySelector:()=>bar,dataset:{}};
 const selection={rect:{left:180,width:100,top:205,bottom:225},dock:{left:100,top:150}};
 const ctx={$:id=>({transcriptFormatTools:tools,transcriptFormatPalette:palette,feedwrap:{getBoundingClientRect:()=>({top:70,bottom:600})}})[id],innerWidth:900,innerHeight:600,hideTranscriptFormatTools(){}};
 vm.createContext(ctx);ctx.selection=selection;vm.runInContext('let transcriptFormatSelection=selection;'+body('positionTranscriptFormatTools'),ctx);
 ctx.positionTranscriptFormatTools();assert.equal(tools.style.top,'150px');assert.equal(tools.style.left,'100px');
});
