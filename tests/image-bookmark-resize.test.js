const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
test('rebuilding the same image on resize does not replay bookmark entrance',()=>{
 const start=html.indexOf("  const wrap=$('feedwrap'), feed=$('feed'), preview=$('transcriptImagePreview');");
 const end=html.indexOf("\n$('feedwrap').addEventListener('dragenter'",start);
 let mutation,resize,frame,enters=0;const exits=[];
 const styles=()=>({setProperty(){}}),classes=new Set();
 const classList={contains:x=>classes.has(x),add:x=>{classes.add(x);if(x==='bookmark-enter')enters++;},remove:x=>classes.delete(x)};
 const art={src:''},surface={firstElementChild:art,style:styles(),addEventListener(){}};
 const preview={firstElementChild:surface,hidden:true,style:styles(),classList,matches:()=>false,appendChild(){},addEventListener(){},querySelector:()=>({addEventListener(){}})};
 const wrap={scrollTop:100,classList:{contains:()=>true},getBoundingClientRect:()=>({top:0,left:300,right:1000,bottom:700,height:700}),addEventListener(){}};
 const image=(file='a.png')=>({src:file,naturalWidth:100,isConnected:true,classList:{contains:()=>false},closest:()=>({dataset:{imageSessionId:'one',imageFile:file,noteIndex:'0',noteContentIndex:'0'}}),getBoundingClientRect:()=>({top:-200,bottom:-100,height:100,width:100})});
 let items=[image()];const feed={querySelectorAll:()=>items,addEventListener(){}};
 const ctx=vm.createContext({$:id=>({feedwrap:wrap,feed,transcriptImagePreview:preview}[id]),matchMedia:()=>({matches:false}),document:{createElement:()=>({setAttribute(){},remove(){this.removed=true;},animate(keys,timing){const animation={keys,timing,node:this};exits.push(animation);return animation;}}),body:{classList:{contains:()=>false}}},innerWidth:1100,innerHeight:800,
 requestAnimationFrame:fn=>{frame=fn;return 1;},MutationObserver:class{constructor(fn){mutation=fn;}observe(){}},ResizeObserver:class{constructor(fn){resize=fn;}observe(){}}});
 vm.runInContext('{'+html.slice(start,end),ctx);
 mutation();frame();assert.equal(enters,1);
 items=[image()];mutation();resize();frame();assert.equal(enters,1,'same image rebuilt during resize must not animate');assert.equal(exits.length,0);
 items=[image('b.png')];mutation();frame();assert.equal(enters,2,'a different course image still animates');
 assert.equal(exits.length,1,'old handle exits while new handle enters');
 assert.equal(exits[0].keys[1].translate,'14px 0');assert.equal(exits[0].keys[1].opacity,0);
 items=[image('b.png')];mutation();frame();assert.equal(exits.length,1,'refresh must not restart the exit');
 exits[0].onfinish();assert.equal(exits[0].node.removed,true);
});
