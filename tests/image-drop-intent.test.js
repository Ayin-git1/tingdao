const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const html=fs.readFileSync('index.html','utf8');
function load(){const start=html.indexOf('function resolveImageDropIntent(');assert.ok(start>=0);const ctx=vm.createContext({});runFunction('resolveImageAsideWidth',ctx);vm.runInContext(html.slice(start,html.indexOf('\n}',start)+2),ctx);return ctx.resolveImageDropIntent;}
const row={dataset:{rowId:'r'},getBoundingClientRect:()=>({top:0,height:100})};
function intent(x,y,width=800,previousIntent=null){return load()({event:{clientX:100+x*width,clientY:y*100},row,content:{getBoundingClientRect:()=>({left:100,width})},imageWidth:260,previousIntent});}
test('Y edges override aside; center uses row midpoint',()=>{assert.equal(intent(.95,.1).position,'before');assert.equal(intent(.05,.9).position,'after');assert.equal(intent(.5,.4).position,'before');assert.equal(intent(.5,.6).position,'after');});
test('content X excludes gutter and enforces width limits',()=>{assert.equal(intent(.1,.5).side,'left');assert.equal(intent(.9,.5).side,'right');assert.equal(intent(.9,.5,100).mode,'inline');assert.equal(intent(.9,.5,700).side,'right');});
test('hysteresis applies only to same row',()=>{assert.equal(intent(.68,.5,800,{mode:'aside',side:'right',rowId:'r'}).side,'right');assert.equal(intent(.65,.5,800,{mode:'aside',side:'right',rowId:'r'}).mode,'inline');assert.equal(intent(.32,.5,800,{mode:'aside',side:'left',rowId:'r'}).side,'left');assert.equal(intent(.32,.5,800,{mode:'aside',side:'left',rowId:'other'}).mode,'inline');});
function runFunction(name,context,async=false){if(name==='commitImageDrop')context.removeTranscriptImageDragGhost=()=>{};if(['resetImageAsideFlow','applyImageAsideFlow'].includes(name))runFunction('syncImageAsideHover',context);const start=html.indexOf(`function ${name}(`);vm.runInContext((async?'async ':'')+html.slice(start,html.indexOf('\n}',start)+2),context);}
test('drop uses preview intent and existing insertion path',async()=>{const calls=[];const ctx=vm.createContext({imageDropMediaVersion:0,imageDropPreviewMedia:null,currentDropIntent:{mode:'aside',side:'left',rowId:'r'},transcriptDraggedImage:null,clearImageDropPreview:()=>calls.push('clear'),insertTranscriptImageFiles:(files,target,native)=>calls.push({files,target,native})});runFunction('commitImageDrop',ctx,true);await ctx.commitImageDrop(['a'],{time:3,intent:{mode:'inline',position:'before',rowId:'r'}},true);assert.equal(calls[1].target.intent.side,'left');assert.equal(calls[1].native,true);});
test('deleting one image preserves structured text and other images',async()=>{const requests=[];const ctx=vm.createContext({view:{id:'p'},api:async(path,body)=>{requests.push({path,body});return {notes:[]};},renderTimelineNotes(){},refreshHistory(){},toast(){}});runFunction('deleteTranscriptMainImage',ctx,true);await ctx.deleteTranscriptMainImage({noteIndex:0,contentIndex:1,note:{t:0,text:'',content:[{type:'text',text:'keep'},{type:'image',file:'a'},{type:'image',file:'b'}]}});assert.equal(requests[0].path,'/api/timeline_note_update');assert.equal(requests[0].body.content.length,2);assert.equal(requests[0].body.content[0].text,'keep');assert.equal(requests[0].body.content[1].file,'b');});
test('deleting final image removes empty storage record',async()=>{const requests=[];const ctx=vm.createContext({view:{id:'p'},api:async(path,body)=>{requests.push({path,body});return {notes:[]};},renderTimelineNotes(){},refreshHistory(){},toast(){}});runFunction('deleteTranscriptMainImage',ctx,true);await ctx.deleteTranscriptMainImage({noteIndex:0,contentIndex:0,note:{t:0,text:'',content:[{type:'image',file:'a'}]}});assert.equal(requests[0].path,'/api/timeline_note_delete');});
test('aside preview waits once per target and cancels pending activation',()=>{
  let activations=0,timer,cleared=0;
  const ctx=vm.createContext({imageDropPreviewTimer:null,imageDropPreviewKey:null,imageDropPreviewPhase:'inline',
    setTimeout:(fn,ms)=>{assert.equal(ms,120);timer=fn;return 1;},clearTimeout:()=>cleared++,activateImageDropPreview:()=>activations++});
  runFunction('scheduleImageDropPreview',ctx);
  ctx.scheduleImageDropPreview('r:right');ctx.scheduleImageDropPreview('r:right');assert.equal(activations,0);timer();assert.equal(activations,1);
  ctx.scheduleImageDropPreview('r:left');assert.ok(cleared);assert.equal(ctx.imageDropPreviewPhase,'candidate');
});
test('preview cleanup restores an existing saved aside layout',()=>{
 const classes=new Set(['image-aside-text','image-aside-preview']),props=new Map([['--image-aside-space','276px'],['--image-aside-overlap','80px']]);
 const content={dataset:{imageSide:'left'},classList:{remove:(...names)=>names.forEach(n=>classes.delete(n)),toggle:(n,on)=>on?classes.add(n):classes.delete(n)},style:{setProperty:(n,v)=>props.set(n,v),removeProperty:n=>props.delete(n)}};
 const ctx=vm.createContext({imageDropPreviewStyles:new Map([[content,{aside:true,side:'right',properties:[['--image-aside-space','336px'],['--image-aside-overlap','100px']]}]])});
 runFunction('resetImageAsideFlow',ctx);ctx.resetImageAsideFlow(true);
 assert.equal(content.dataset.imageSide,'right');assert.equal(props.get('--image-aside-space'),'336px');assert.ok(classes.has('image-aside-text'));assert.ok(!classes.has('image-aside-preview'));
});
test('image flow narrows multiple intersecting paragraphs and stops below image',()=>{
 const contents=Array.from({length:5},(_,i)=>({dataset:{},classList:{add(){}},style:{setProperty(name,value){this[name]=value;}},getBoundingClientRect(){return {top:i*100,width:800,height:60};}}));
 const rows=contents.map(c=>({querySelector:()=>c}));
 const ctx=vm.createContext({$:()=>({querySelectorAll:()=>rows}),imageDropPreviewStyles:new Map()});runFunction('applyImageAsideFlow',ctx);
 ctx.applyImageAsideFlow(rows[0],260,240,'right');
 assert.equal(contents[0].style['--image-aside-space'],'276px');assert.equal(contents[1].dataset.imageSide,'right');
 assert.equal(contents[2].style['--image-aside-overlap'],'40px');assert.equal(contents[3].style['--image-aside-space'],undefined);
});
test('external images default to equal column widths independent of intrinsic size',()=>{
 const ctx=vm.createContext({view:{id:'p'},transcriptDraggedImage:null,currentDropIntent:null,imageDropPreviewMedia:{width:100,height:50},imageDropPreviewRects:new Map()});
 const content={getBoundingClientRect:()=>({left:66,width:800})};const row={dataset:{rowId:'r',t:'0'},querySelector:()=>content,getBoundingClientRect:()=>({top:0,bottom:100,height:100})};
 ctx.$=id=>id==='transcriptNoteLayer'?{hidden:true}:id==='feedwrap'?{getBoundingClientRect:()=>({left:0,right:900,top:0,bottom:400})}:{querySelectorAll:()=>[row]};
 runFunction('resolveImageAsideWidth',ctx);runFunction('resolveImageDropIntent',ctx);runFunction('transcriptImageDropTarget',ctx);
 assert.equal(ctx.transcriptImageDropTarget(850,50).imageWidth,392);
});
test('current 538px transcript defaults to equal columns and supports resizing',()=>{
 assert.equal(intent(.1,.5,538).side,'left');assert.equal(intent(.9,.5,538).side,'right');
 const ctx=vm.createContext({});runFunction('resolveImageAsideWidth',ctx);
 assert.equal(ctx.resolveImageAsideWidth(538),261);assert.equal(ctx.resolveImageAsideWidth(538,180),180);
 assert.equal(ctx.resolveImageAsideWidth(538,800),474);assert.equal(ctx.resolveImageAsideWidth(100),0);
});

test('hover bounds track aside width and restore with text layout',()=>{
 const properties=new Map(),row={dataset:{},style:{setProperty:(n,v)=>properties.set(n,v),removeProperty:n=>properties.delete(n)}};
 let aside=true;const content={parentElement:row,dataset:{imageSide:'right'},classList:{contains:()=>aside},style:{getPropertyValue:n=>n==='--image-aside-space'?'277px':'80px'}};
 const ctx=vm.createContext({});runFunction('syncImageAsideHover',ctx);ctx.syncImageAsideHover(content);
 assert.equal(properties.get('--image-hover-space'),'277px');assert.equal(row.dataset.imageHoverSide,'right');
 aside=false;ctx.syncImageAsideHover(content);assert.equal(properties.size,0);assert.equal(row.dataset.imageHoverSide,undefined);
});

test('headings overlapping an aside image reserve horizontal space on either side',()=>{
 for(const side of ['left','right']){
  const make=(top)=>({dataset:{},classList:{add(){},contains:()=>false},style:{setProperty(n,v){this[n]=v;}},getBoundingClientRect:()=>({top,width:800,height:60})});
  const text=make(0),h1=make(80),h2=make(160),below=make(300);
  for(const heading of [h1,h2,below])heading.matches=selector=>selector==='.transcript-heading';
  const anchor={querySelector:()=>text};const rows=[anchor,h1,h2,below];
  const ctx=vm.createContext({$:()=>({querySelectorAll:()=>rows}),imageDropPreviewStyles:new Map()});
  runFunction('applyImageAsideFlow',ctx);ctx.applyImageAsideFlow(anchor,260,240,side);
  assert.equal(h1.style['--image-aside-space'],'276px');assert.equal(h2.style['--image-aside-space'],'276px');
  assert.equal(h1.dataset.imageSide,side);assert.equal(h2.dataset.imageSide,side);
  assert.equal(below.style['--image-aside-space'],undefined);
 }
 assert.doesNotMatch(html,/图片位置已保存/);
});

test('oversized images may enter aside mode when deliberately dragged to either side',()=>{
 const resolve=load();
 const content={getBoundingClientRect:()=>({left:0,width:500})};
 for(const x of [20,480]){
  assert.equal(resolve({event:{clientX:x,clientY:50},row,content,imageWidth:351,
    previousIntent:{mode:'aside',side:x<250?'left':'right',rowId:'r'}}).mode,'aside');
  assert.equal(resolve({event:{clientX:x,clientY:50},row,content,imageWidth:350}).mode,'aside');
 }
});


test('large image moved from inline to either column previews and saves at 50 percent',async()=>{
 const saved=[];
 const ctx=vm.createContext({view:{id:'p'},transcriptDraggedImage:{node:{layout:'inline',displayWidth:700},row:{classList:{remove(){}}}},
  currentDropIntent:null,imageDropPreviewRects:new Map(),imageDropMediaVersion:0,imageDropPreviewMedia:null,
  clearImageDropPreview(){},persistTranscriptMainImageNode:async(source,node)=>saved.push(node)});
 const content={getBoundingClientRect:()=>({left:66,width:800})};
 const row={dataset:{rowId:'r',t:'0'},querySelector:()=>content,getBoundingClientRect:()=>({top:0,bottom:100,height:100})};
 ctx.$=id=>id==='transcriptNoteLayer'?{hidden:true}:id==='feedwrap'?{getBoundingClientRect:()=>({left:0,right:900,top:0,bottom:400})}:{querySelectorAll:()=>[row]};
 runFunction('resolveImageAsideWidth',ctx);runFunction('resolveImageDropIntent',ctx);runFunction('transcriptImageDropTarget',ctx);runFunction('commitImageDrop',ctx,true);
 for(const [x,side] of [[80,'left'],[850,'right']]){
  ctx.transcriptDraggedImage={node:{layout:'inline',displayWidth:700},row:{classList:{remove(){}}}};
  const target=ctx.transcriptImageDropTarget(x,50);
  assert.equal(target.intent.mode,'aside');assert.equal(target.intent.side,side);assert.equal(target.imageWidth,400);
  await ctx.commitImageDrop([],target);
  assert.equal(saved.at(-1).layout,`aside-${side}`);assert.equal(saved.at(-1).displayWidth,400);
 }
});

test('aside candidate displays the same transparent image through activation',()=>{
 let image=null,flows=0;
 const indicator={dataset:{},style:{},classList:{add(){},toggle(){}},setAttribute(){},replaceChildren(){image=null;},querySelector:()=>image,appendChild(node){image=node;}};
 const bounds={left:100,right:900,width:800,top:20};
 const ctx=vm.createContext({currentImageDropTarget:{content:{getBoundingClientRect:()=>bounds},row:{},rowRect:{top:20,bottom:120,height:100},intent:{mode:'aside',side:'right'},imageWidth:260},
 imageDropPreviewPhase:'candidate',imageDropPreviewMedia:{src:'test.png',width:520,height:260},
 resetImageAsideFlow(){},applyImageAsideFlow(){flows++;},$:()=>indicator,
 document:{createElement:()=>({getAttribute(){return this.src;}})}});
 runFunction('paintImageDropPreview',ctx);ctx.paintImageDropPreview();
 assert.equal(image?.src,'test.png');const candidate=image;assert.equal(flows,0);
 ctx.imageDropPreviewPhase='active';ctx.paintImageDropPreview();assert.equal(image,candidate);assert.equal(flows,1);
 ctx.imageDropPreviewMedia=null;ctx.imageDropPreviewPhase='candidate';ctx.paintImageDropPreview();
 assert.equal(image,null);
});

test('aside ghost has no solid stage or reveal and avoidance is linear',()=>{
 const aside=html.match(/#transcriptImageDropIndicator\[data-mode="aside"\]\{([^}]+)\}/)[1];
 assert.match(aside,/background:transparent/);assert.match(aside,/transition:none/);
 assert.doesNotMatch(html,/imageDropGhostReveal/);
 assert.match(html,/padding-left 160ms linear, padding-right 160ms linear/);
 assert.match(html,/transition:left 160ms linear,width 160ms linear,opacity 160ms linear/);
 assert.match(html,/@media\(prefers-reduced-motion:reduce\)[^\n]*\.transcript-heading[^\n]*transition:none/);
});

test('restored aside flow measures final wrapping before deciding which rows avoid the image',()=>{
 for(const side of ['left','right']){
  const contents=[];
  for(let i=0;i<4;i++)contents.push({dataset:{},classList:{add(){},contains:()=>false},
   style:{transition:'',setProperty(n,v){this[n]=v;}},
   getBoundingClientRect(){return {top:contents.slice(0,i).reduce((sum,c)=>sum+c.getBoundingClientRect().height,0),width:800,
    height:(this.measuredHeight=this.style['--image-aside-space']&&this.style.transition==='none'?180:this.measuredHeight||60)};}});
  const rows=contents.map(content=>({querySelector:()=>content}));
  const ctx=vm.createContext({$:()=>({querySelectorAll:()=>rows}),imageDropPreviewStyles:new Map()});
  runFunction('applyImageAsideFlow',ctx);ctx.applyImageAsideFlow(rows[0],260,240,side);
  assert.equal(contents[2].style['--image-aside-space'],undefined);
  assert.equal(contents[0].style.transition,'');
 }
});
