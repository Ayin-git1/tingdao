const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const start=html.indexOf('function syncRecordDock(');
const source=html.slice(start,html.indexOf('\n}',start)+2);
for(const entering of [true,false])test(`${entering?'attach':'detach'} keeps the blur button ancestor opaque throughout its movement`,()=>{
 const classes=new Set(entering?[]:['attached']);const animations=[];
 const dock={classList:{contains:key=>classes.has(key),toggle:(key,on)=>on?classes.add(key):classes.delete(key),remove:(...keys)=>keys.forEach(key=>classes.delete(key))},getBoundingClientRect:()=>({left:600,top:600}),getAnimations:()=>[],style:{setProperty(){}},animate:frames=>animations.push(frames)};
 const bar={classList:{contains:()=>true},parentElement:{clientWidth:900},getBoundingClientRect:()=>({left:350,top:600,width:400,height:50})};
 const context=vm.createContext({$:id=>id==='dockgrp'?dock:bar,state:'idle',view:entering?{}:null,window:{innerWidth:1200,innerHeight:800,matchMedia:()=>({matches:false})},syncAllNotesDock(){}});
 vm.runInContext(source,context);context.syncRecordDock();
 assert.equal(animations.length,1);
 for(const frame of animations[0])assert.equal(frame.opacity??1,1,'ancestor opacity changes the backdrop root');
 assert.ok(animations[0].every(frame=>frame.transform),'magnetic movement remains animated');
});
