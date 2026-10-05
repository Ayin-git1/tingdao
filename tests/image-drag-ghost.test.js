const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test');
const html=fs.readFileSync('index.html','utf8');
function source(name){const start=html.indexOf(`function ${name}(`);return html.slice(start,html.indexOf('\n}',start)+2);}
test('image ghost follows pointer, limits tilt and cleans up',()=>{
 const classes=new Set();let appended=0,removed=0;
 const ghost={style:{},appendChild(){},remove(){removed++;}};
 const context=vm.createContext({transcriptImageDragGhost:null,transcriptImageDragLastX:0,transcriptImageAutoScroller:null,
 transcriptDraggedImage:{row:{getBoundingClientRect:()=>({width:200}),querySelector:()=>({cloneNode:()=>({})})}},
 document:{createElement:()=>ghost,body:{appendChild(){appended++;},classList:{add:n=>classes.add(n),remove:n=>classes.delete(n)}}},
 window:{matchMedia:()=>({matches:false})}});
 vm.runInContext(source('moveTranscriptImageDragGhost')+'\n'+source('removeTranscriptImageDragGhost'),context);
 context.moveTranscriptImageDragGhost({clientX:100,clientY:80});
 assert.equal(ghost.style.width,'200px');assert.equal(ghost.style.transform,'translate(84px, 66px) rotate(0deg)');
 context.moveTranscriptImageDragGhost({clientX:200,clientY:90});assert.match(ghost.style.transform,/rotate\(5deg\)/);assert.equal(appended,1);
 context.window.matchMedia=()=>({matches:true});context.moveTranscriptImageDragGhost({clientX:0,clientY:90});assert.match(ghost.style.transform,/rotate\(0deg\)/);
 context.removeTranscriptImageDragGhost();context.removeTranscriptImageDragGhost();assert.equal(removed,1);assert.equal(classes.size,0);assert.equal(context.transcriptImageDragGhost,null);
});
test('sidebar ghost front and back use theme-aware resting material',()=>{
 for(const selector of ['gcard','gback']){
  const rule=html.match(new RegExp(`#sbGhost \\.${selector}\\{([^}]+)\\}`))[1];
  for(const token of ['background','border','backdrop-filter'])assert.ok(rule.includes(`var(--material-rest-${token})`));
 }
 assert.doesNotMatch(html,/html\[data-appearance="dark"\] #sbGhost \.(gcard|gback)\s*\{/);
});

test('scrolling shifts cached row bounds and re-hits the stationary image pointer',()=>{
 const row={},point={clientX:200,clientY:350};let hit,shown;
 const context=vm.createContext({imageDropPreviewScrollTop:100,
 imageDropPreviewRects:new Map([[row,{top:200,bottom:300,height:100}]]),
 $:()=>({scrollTop:140}),transcriptImageDropTarget(x,y){hit=[x,y];return {row};},
 showTranscriptImageDropIndicator:target=>shown=target,clearImageDropPreview(){}});
 vm.runInContext(source('refreshTranscriptImageDragTarget'),context);
 context.refreshTranscriptImageDragTarget(point);
 assert.deepEqual(hit,[200,350]);assert.equal(shown.row,row);
 assert.equal(context.imageDropPreviewRects.get(row).top,160);assert.equal(context.imageDropPreviewRects.get(row).bottom,260);
 context.refreshTranscriptImageDragTarget(point);assert.equal(context.imageDropPreviewRects.get(row).top,160);
});
