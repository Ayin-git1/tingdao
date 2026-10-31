const test = require('node:test'), assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');

function functionCode(name) {
 const start=html.indexOf(`function ${name}(`);
 assert.ok(start>=0, `${name} 尚未实现`);
 return html.slice(html.slice(start-6,start)==='async '?start-6:start, html.indexOf('\n}',start)+2);
}
test('first-frame gate has no dismiss control and profile can be changed in personalization',()=>{
 assert.match(html, /data-profile-required/);
 const start=html.indexOf('id="profileGate"');
 const gate=html.slice(start,html.indexOf('<div class="modal" id="noteImportModal"',start));
 assert.ok(start>=0);
 assert.match(gate,/id="profileName"/);
 assert.doesNotMatch(gate,/data-dlg="cancel"|取消|关闭/);
 const section=html.slice(html.indexOf('id="sec-appearance"'),html.indexOf('id="sec-sound"'));
 assert.match(section,/id="setUsername"/);
 assert.match(html,/id="brandUsername"/);
});
test('profile save rejects invalid names, remains gated on failure, and updates after server success',async()=>{
 const input={value:'中文'},error={textContent:''},button={disabled:false};
 let saved=[],applied=[];
 const ctx=vm.createContext({$:id=>({profileName:input,profileNameError:error,profileSave:button}[id]),
   async api(path,body){saved.push([path,body]);return {ok:true,username:body.username};},
   applyUsername:name=>applied.push(name),setProfileGate:needed=>{ctx.gated=needed;}});
 vm.runInContext(functionCode('submitProfileName'),ctx);
 ctx.gated=true;
 await ctx.submitProfileName();
 assert.equal(saved.length,0);assert.equal(ctx.gated,true);
 input.value='Ayin';await ctx.submitProfileName();
 assert.deepEqual(JSON.parse(JSON.stringify(saved)),[['/api/profile',{username:'Ayin'}]]);
 assert.deepEqual(applied,['Ayin']);assert.equal(ctx.gated,false);assert.equal(button.disabled,false);
 ctx.gated=true;ctx.api=async()=>({error:'无法保存'});await ctx.submitProfileName();
 assert.equal(ctx.gated,true);assert.equal(error.textContent,'无法保存');
});
test('profile name gets its first letter capitalized instead of an error',async()=>{
 const input={value:'doris'},error={textContent:''},button={disabled:false};
 let saved=[];
 const ctx=vm.createContext({$:id=>({profileName:input,profileNameError:error,profileSave:button}[id]),
   async api(path,body){saved.push(body.username);return {ok:true,username:body.username};},
   applyUsername(){},setProfileGate(){}});
 vm.runInContext(functionCode('submitProfileName'),ctx);
 await ctx.submitProfileName();
 assert.deepEqual(saved,['Doris']);assert.equal(error.textContent,'');
});
