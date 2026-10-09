const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
function source(name){const start=html.indexOf(`function ${name}(`);assert.notEqual(start,-1,name);return html.slice(start,html.indexOf('\n}',start)+2);}
test('editing and restoring keep the aside text container and image nodes',()=>{
  const tx={innerHTML:'',style:{paddingRight:'316px'}};
  const figure={},divider={};
  const row={dataset:{raw:'old'},querySelector:()=>tx,children:[tx,figure,divider]};
  const ctx={segOf:()=>null,spkBadge:()=>'<i>1</i>',esc:v=>v,fixDot:()=>'<i>edited</i>',refreshTranscriptImageAsideFlow(){}};
  vm.createContext(ctx);vm.runInContext(source('transcriptMarkerInk')+source('transcriptHighlightColor')+source('transcriptFormatCSS')+source('transcriptFormattedHtml')+source('renderSegmentText'),ctx);
  ctx.renderSegmentText(row,'new',true);
  assert.match(tx.innerHTML,/contenteditable="true"/);
  assert.equal(tx.style.paddingRight,'316px');
  assert.deepEqual(row.children,[tx,figure,divider]);
  ctx.renderSegmentText(row,'saved');
  assert.match(tx.innerHTML,/tx-focus.*saved/);
  assert.doesNotMatch(tx.innerHTML,/contenteditable/);
  assert.equal(row.dataset.raw,'saved');
});
test('aside flow includes saved notes and both inline cards, on either side',()=>{
  for(const side of ['left','right']){
    const make=(kind,top)=>{
      const properties={};const classes=new Set();
      const content={style:{setProperty:(k,v)=>properties[k]=v},dataset:{},classList:{add:c=>classes.add(c)},getBoundingClientRect:()=>({top,width:800,height:50})};
      const row={matches:()=>['heading','noteEditor','editbar'].includes(kind),querySelector:()=>content};
      if(row.matches())Object.assign(row,content);
      return {row,content:row.matches()?row:content,properties,classes};
    };
    const items=['speech','note','noteEditor','editbar','heading','speech'].map((kind,i)=>make(kind,i*50));
    let selector;
    const ctx={$:()=>({querySelectorAll:s=>{selector=s;return s.includes('.tn-layer')?items.map(x=>x.row):[items[0].row,items[4].row,items[5].row];}}),syncImageAsideHover(){},Math};
    vm.createContext(ctx);vm.runInContext(source('applyImageAsideFlow'),ctx);
    ctx.applyImageAsideFlow(items[0].row,300,230,side);
    for(const item of items.slice(0,5)){
      assert.equal(item.content.dataset.imageSide,side);
      assert.equal(item.properties['--image-aside-space'],'316px');
    }
    assert.equal(items[5].content.dataset.imageSide,undefined);
    assert.match(selector,/\.seg:not\(\.sum\)/);
  }
});
