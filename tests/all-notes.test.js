const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const html=fs.readFileSync('index.html','utf8');
function source(name){const start=html.indexOf(`function ${name}(`);return html.slice(start,html.indexOf('\n}',start)+2);}
const context=vm.createContext({});
vm.runInContext(source('transcriptOutlineNavigationItems')+'\n'+source('allNotesGroups'),context);
test('notes sort chronologically, merge consecutive topics and reset H2 at the next H1',()=>{
 const groups=context.allNotesGroups([{t:80,text:'d'},{t:5,text:'a'},{t:25,text:'b'},{t:28,content:[{type:'image',file:'a.png'}]}],[{t:0,level:1,title:'Chapter'},{t:20,level:2,title:'Topic'},{t:70,level:1,title:'Next'}]);
 assert.deepEqual(JSON.parse(JSON.stringify(groups.map(g=>[g.t,g.title,g.items.length]))),[[5,'Chapter',1],[25,'Topic',2],[80,'Next',1]]);
});
test('empty notes are omitted and pre-outline notes fall back to H1',()=>{
 const groups=context.allNotesGroups([{t:0,text:''},{t:2,text:'before'}],[{t:10,level:1,title:'Later'}]);
 assert.equal(groups.length,1);assert.equal(groups[0].title,'H1');
});
test('legacy outline levels retain their H1 and H2 grouping',()=>{
 const groups=context.allNotesGroups([{t:5,text:'a'},{t:15,text:'b'}],[{t:0,level:2,title:'Chapter'},{t:10,level:4,title:'Topic'}]);
 assert.equal(groups[0].title,'Chapter');assert.equal(groups[1].title,'Topic');
});
test('entry animation is guarded by the previous view and respects reduced motion',()=>{
 assert.match(html,/const enteringNotes=view===null/);assert.match(html,/if\(enteringNotes\)animateNotesEntry\(\)/);
 assert.match(source('animateNotesEntry'),/prefers-reduced-motion/);
 const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
 for(const script of scripts)new vm.Script(script[1]);
});
