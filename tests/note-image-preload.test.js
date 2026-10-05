const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');const start=html.indexOf('const noteImagePreloads=new Map();');const source=html.slice(start,html.indexOf('\nasync function loadSession',start));
test('reentering a project reuses decoded images and preserves URL escaping',async()=>{
 const images=[];const context=vm.createContext({Image:class{constructor(){images.push(this);}decode(){return Promise.resolve();}}});
 vm.runInContext(source,context);
 const session={id:'a b',notes:[{content:[{type:'image',file:'note-images/a b.png'},{type:'image',file:'note-images/a b.png'}]}]};
 await context.preloadNoteImages(session);await context.preloadNoteImages(session);
 assert.equal(images.length,1);assert.equal(images[0].src,'/note-image/a%20b/a%20b.png');
});
test('broken images do not block entry and may retry later',async()=>{
 let attempts=0;const context=vm.createContext({Image:class{decode(){attempts++;return Promise.reject(new Error('missing'));}}});vm.runInContext(source,context);
 const session={id:'test',notes:[{content:[{type:'image',file:'missing.png'}]}]};
 await context.preloadNoteImages(session);await context.preloadNoteImages(session);assert.equal(attempts,2);
});
