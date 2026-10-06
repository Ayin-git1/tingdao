const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const source=html.slice(html.indexOf('function clearFind('),html.indexOf('function navFind('));
function row(){return {writes:0,removed:[],classList:{contains:()=>false,remove(name){this.owner.removed.push(name);}},set innerHTML(value){this.writes++;this.html=value;}};}
function harness(){
 const rows=Array.from({length:5000},row);rows.forEach(row=>row.classList.owner=row);
 const counter={textContent:'2/3'};
 const context=vm.createContext({segEls:rows,findHits:[{el:rows[10]},{el:rows[10]},{el:rows[4000]}],findPos:1,segHtml:()=>'<span>原文</span>',$:()=>counter});
 vm.runInContext(source,context);return {rows,counter,context};
}
test('cleanup restores only previously matched rows and deduplicates repeated hits',()=>{
 const {rows,context,counter}=harness();context.clearFind(false);
 assert.equal(rows.reduce((sum,row)=>sum+row.writes,0),2);
 assert.equal(rows[10].writes,1);assert.equal(rows[4000].writes,1);
 assert.deepEqual(rows[10].removed,['hl']);assert.equal(context.findHits.length,0);assert.equal(context.findPos,-1);
 assert.equal(counter.textContent,'2/3');
});
test('empty and repeated cleanup leave untouched rows and their DOM intact',()=>{
 const {rows,context,counter}=harness();context.clearFind();context.clearFind();
 assert.equal(counter.textContent,'0/0');assert.equal(rows.reduce((sum,row)=>sum+row.writes,0),2);
});
test('cleanup after project switch never rewrites new project rows',()=>{
 const {rows,context}=harness();const next=row();next.classList.owner=next;context.segEls=[next];
 context.clearFind();assert.equal(next.writes,0);assert.equal(rows[10].writes,1);
});
