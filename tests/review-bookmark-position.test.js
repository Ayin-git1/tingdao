const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
test('review bookmark follows the manuscript throughout sidebar closing and reopening',()=>{
 const place=html.match(/function reviewPlace\(\)\{[^]*?\n\}/)[0];
 const start=html.indexOf("  window.addEventListener('resize',",html.indexOf('(function wireReview(){'));
 const end=html.indexOf('\n})();',start);
 let left=300,observe,resize;const wrap={getBoundingClientRect:()=>({left,top:80,height:700})};
 const bookmark={hidden:false,style:{}},panel={style:{},classList:{contains:()=>false}};
 const ctx=vm.createContext({panel,$:id=>({feedwrap:wrap,reviewBookmark:bookmark,reviewPanel:panel}[id]),
 window:{addEventListener:(name,fn)=>resize=fn},ResizeObserver:class{constructor(fn){this.fn=fn;}observe(target){assert.equal(target,wrap);observe=this.fn;}},reviewApplyPush(){}});
 vm.runInContext(place+'\n'+html.slice(start,end),ctx);ctx.reviewPlace();
 assert.equal(typeof observe,'function','manuscript geometry must be observed independently of window resizing');
 for(const x of [240,120,9,80,200,300]){left=x;observe();assert.equal(bookmark.style.left,x+'px');assert.equal(panel.style.left,(x+12)+'px');}
 left=350;resize();assert.equal(bookmark.style.left,'350px');
});
