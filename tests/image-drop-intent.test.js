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
 const classes=new Set(['image-aside-text','image-aside-preview']),props=new Map([['--image-aside-right-space','276px'],['--image-aside-right-overlap','80px']]);
 const content={dataset:{imageSide:'left'},classList:{remove:(...names)=>names.forEach(n=>classes.delete(n)),toggle:(n,on)=>on?classes.add(n):classes.delete(n)},style:{setProperty:(n,v)=>props.set(n,v),removeProperty:n=>props.delete(n)}};
 const ctx=vm.createContext({imageDropPreviewStyles:new Map([[content,{aside:true,side:'right',properties:[['--image-aside-right-space','336px'],['--image-aside-right-overlap','100px']]}]])});
 runFunction('resetImageAsideFlow',ctx);ctx.resetImageAsideFlow(true);
 assert.equal(content.dataset.imageSide,'right');assert.equal(props.get('--image-aside-right-space'),'336px');assert.ok(classes.has('image-aside-text'));assert.ok(!classes.has('image-aside-preview'));
});
test('image flow narrows multiple intersecting paragraphs and stops below image',()=>{
 const contents=Array.from({length:5},(_,i)=>({dataset:{},classList:{add(){}},matches:()=>true,querySelector:()=>({getBoundingClientRect:()=>({height:60})}),style:{setProperty(name,value){this[name]=value;},getPropertyValue(name){return this[name]||'';}},getBoundingClientRect(){return {top:i*100,width:800,height:60};}}));
 const rows=contents.map(c=>({classList:{add(){},remove(){}},querySelector:()=>c}));
 const ctx=vm.createContext({$:()=>({querySelectorAll:()=>rows}),imageDropPreviewStyles:new Map()});runFunction('applyImageAsideFlow',ctx);
 ctx.applyImageAsideFlow(rows[0],260,240,'right');
 assert.equal(contents[0].style['--image-aside-right-space'],'276px');assert.equal(contents[1].dataset.imageSide,'right');
 // 第 1 段整段都在图片旁：占位块只到文字底部；第 3 段穿过图片底部：只占到图片底部加 6px 呼吸
 assert.equal(contents[0].style['--image-aside-right-overlap'],'60px');
 assert.equal(contents[2].style['--image-aside-right-overlap'],'46px');assert.equal(contents[3].style['--image-aside-right-space'],undefined);
});
test('a paragraph touching images on both sides keeps both spacers instead of the later one winning',()=>{
 // 文字高度随占位块变化：只要还有一侧到不了文字底部，文字就变宽变矮
 const style={setProperty(n,v){this[n]=v;},getPropertyValue(n){return this[n]||'';}};
 const number=n=>parseFloat(style[n])||0;
 const textHeight=()=>Math.min(number('--image-aside-left-overlap')||Infinity,number('--image-aside-right-overlap')||Infinity)>=120?120:90;
 const content={dataset:{},classList:{add(){}},matches:()=>true,style,querySelector:()=>({getBoundingClientRect:()=>({height:textHeight()})}),getBoundingClientRect:()=>({top:0,width:800,height:120})};
 const row={classList:{add(){},remove(){}},querySelector:()=>content};
 const ctx=vm.createContext({$:()=>({querySelectorAll:()=>[row]}),imageDropPreviewStyles:new Map()});runFunction('applyImageAsideFlow',ctx);
 ctx.applyImageAsideFlow(row,260,300,'right');
 ctx.applyImageAsideFlow(row,200,40,'left');
 assert.equal(content.dataset.imageSide,'right left');
 assert.equal(style['--image-aside-right-space'],'276px');assert.equal(style['--image-aside-left-space'],'216px');
 // 左侧只到 46px，右侧量出 120 后要收回到实际文字高度 90，不能把段落撑高
 assert.equal(style['--image-aside-left-overlap'],'46px');assert.equal(style['--image-aside-right-overlap'],'90px');
 // 同侧的第二张图不能把已有的避让改小
 ctx.applyImageAsideFlow(row,100,10,'right');
 assert.equal(style['--image-aside-right-space'],'276px');assert.equal(style['--image-aside-right-reach'],'306px');
 assert.equal(content.dataset.imageSide,'right left');
});
test('measuring a paragraph never makes it taller than the image needs, which would drag WebKit scrolling to the bottom',()=>{
 // WebKit 会为屏幕上方变高的段落补偿滚动位置：测量时的瞬时高度不能超过图片底部
 const seen=[];
 const style={setProperty(n,v){this[n]=v;if(n.endsWith('-overlap'))seen.push(parseFloat(v));},getPropertyValue(n){return this[n]||'';}};
 const content={dataset:{},classList:{add(){}},matches:()=>true,style,querySelector:()=>({getBoundingClientRect:()=>({height:60})}),getBoundingClientRect:()=>({top:0,width:800,height:60})};
 const row={classList:{add(){},remove(){}},querySelector:()=>content};
 const ctx=vm.createContext({$:()=>({querySelectorAll:()=>[row]}),imageDropPreviewStyles:new Map()});runFunction('applyImageAsideFlow',ctx);
 ctx.applyImageAsideFlow(row,260,240,'right');
 assert.ok(seen.length);assert.ok(Math.max(...seen)<=246,`measured with ${Math.max(...seen)}px`);
 assert.equal(style['--image-aside-right-overlap'],'60px');
});
test('layout keeps scrolling stable: no reflow for lazy rows, flow rows stay laid out, height held while measuring',()=>{
 // 这三条的真实症状只在 WebKit 出现（跳转落到文稿底部或中途停住），这里锁住实现约束
 const observer=html.slice(html.indexOf('let transcriptAsideFlowWidth=0'),html.indexOf("$('feedwrap').addEventListener('scroll',scrollFrameUpdate(markTranscriptReadingPosition)"));
 assert.match(observer,/if\(!widthChanged&&flowHeights===transcriptAsideFlowHeights\)\{[^}]*return;\}/);
 assert.ok(observer.indexOf('flowHeights===transcriptAsideFlowHeights')<observer.indexOf('refreshTranscriptImageAsideFlow();'));
 // 比较文字高度而不是段落高度：段落被旧占位块撑着时，字号变小看不出变化
 assert.match(observer,/querySelector\('\.tx-focus,\[contenteditable\]'\)\|\|row\)\.offsetHeight/);
 const reset=html.slice(html.indexOf('function resetImageAsideFlow('),html.indexOf('function applyImageAsideFlow('));
 assert.doesNotMatch(reset,/image-aside-flow/);
 const seen=[];
 const style={height:'',setProperty(n,v){this[n]=v;if(n.endsWith('-overlap'))seen.push(this.height);},getPropertyValue(n){return this[n]||'';}};
 const content={dataset:{},classList:{add(){}},matches:()=>true,style,querySelector:()=>({getBoundingClientRect:()=>({height:60})}),getBoundingClientRect:()=>({top:0,width:800,height:44})};
 const row={classList:{add(){},remove(){}},querySelector:()=>content};
 const ctx=vm.createContext({$:()=>({querySelectorAll:()=>[row]}),imageDropPreviewStyles:new Map()});runFunction('applyImageAsideFlow',ctx);
 ctx.applyImageAsideFlow(row,260,240,'right');
 assert.ok(seen.length&&seen.every(h=>h==='44px'));assert.equal(style.height,'');
});
test('a paragraph with no readable room between two images falls below the shorter one',()=>{
 const style={'--image-aside-left-space':'400px',setProperty(n,v){this[n]=v;},getPropertyValue(n){return this[n]||'';}};
 const content={dataset:{},classList:{add(){}},matches:()=>true,style,querySelector:()=>null,getBoundingClientRect:()=>({top:0,width:700,height:60})};
 const row={classList:{add(){},remove(){}},querySelector:()=>content};
 const ctx=vm.createContext({$:()=>({querySelectorAll:()=>[row]}),imageDropPreviewStyles:new Map()});runFunction('applyImageAsideFlow',ctx);
 ctx.applyImageAsideFlow(row,260,100,'right');
 // 700 - 400 - 276 = 24px，放不下文字：占满余下的 300px，让文字落到图片下方
 assert.equal(style['--image-aside-right-space'],'300px');
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

test('hover and playback highlight span the full row because text below the image returns to full width',()=>{
 assert.doesNotMatch(html,/image-hover-space|imageHoverSide|image-hover-side|syncImageAsideHover/);
 assert.match(html,/#feed \.seg\.image-aside-row\{position:relative;z-index:2;\}/);
});

test('headings overlapping an aside image reserve horizontal space on either side',()=>{
 for(const side of ['left','right']){
  const make=(top)=>({dataset:{},classList:{add(){},remove(){},contains:()=>false},style:{setProperty(n,v){this[n]=v;},getPropertyValue(n){return this[n]||'';}},getBoundingClientRect:()=>({top,width:800,height:60})});
  const text=make(0),h1=make(80),h2=make(160),below=make(300);
  for(const heading of [h1,h2,below])heading.matches=selector=>selector.split(',').includes('.transcript-heading');
  const anchor={classList:{add(){},remove(){}},querySelector:()=>text};const rows=[anchor,h1,h2,below];
  const ctx=vm.createContext({$:()=>({querySelectorAll:()=>rows}),imageDropPreviewStyles:new Map()});
  runFunction('applyImageAsideFlow',ctx);ctx.applyImageAsideFlow(anchor,260,240,side);
  assert.equal(h1.style[`--image-aside-${side}-space`],'276px');assert.equal(h2.style[`--image-aside-${side}-space`],'276px');
  assert.equal(h1.dataset.imageSide,side);assert.equal(h2.dataset.imageSide,side);
  assert.equal(below.style[`--image-aside-${side}-space`],undefined);
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
 assert.match(html,/padding-left 160ms linear,padding-right 160ms linear/);
 assert.match(html,/transition:left 160ms linear,width 160ms linear,opacity 160ms linear/);
 assert.match(html,/@media\(prefers-reduced-motion:reduce\)[^\n]*\.transcript-heading[^\n]*transition:none/);
});

test('restored aside flow measures final wrapping before deciding which rows avoid the image',()=>{
 for(const side of ['left','right']){
  const contents=[];
  // 段落变窄后变高：下一段的位置必须用变窄后的高度来算
  const heightOf=c=>c.style[`--image-aside-${side}-space`]?180:60;
  for(let i=0;i<4;i++)contents.push({dataset:{},classList:{add(){},contains:()=>false},matches:()=>true,
   querySelector(){return {getBoundingClientRect:()=>({height:heightOf(this)})};},
   style:{transition:'',setProperty(n,v){this[n]=v;},getPropertyValue(n){return this[n]||'';}},
   getBoundingClientRect(){return {top:contents.slice(0,i).reduce((sum,c)=>sum+heightOf(c),0),width:800,height:heightOf(this)};}});
  const rows=contents.map(content=>({classList:{add(){},remove(){}},querySelector:()=>content}));
  const ctx=vm.createContext({$:()=>({querySelectorAll:()=>rows}),imageDropPreviewStyles:new Map()});
  runFunction('applyImageAsideFlow',ctx);ctx.applyImageAsideFlow(rows[0],260,240,side);
  assert.equal(contents[0].style[`--image-aside-${side}-overlap`],'180px');
  assert.equal(contents[1].style[`--image-aside-${side}-overlap`],'66px');
  assert.equal(contents[2].style[`--image-aside-${side}-space`],undefined);
  assert.equal(contents[0].style.transition,'');
 }
});

