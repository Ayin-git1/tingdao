const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
test('patch boot acknowledges only after startup work succeeds and never notifies',async()=>{
  const html=fs.readFileSync('index.html','utf8');
  const start=html.indexOf('async function confirmFrontendPatch(');
  assert.ok(start>=0,'ready handshake exists');
  const source=html.slice(start,html.indexOf('\n}',start)+2).replace('__TINGDAO_PATCH_TOKEN__','test-token');
  for(const failed of ['', 'status', 'history', 'settings']){
    const calls=[];
    const context=vm.createContext({fetchStatus:async()=>({state:'idle'}),
      applyStatus:()=>{calls.push('status');if(failed==='status')throw Error('broken startup');},
      frontendStartupTasks:[Promise.resolve(failed!=='settings')],
      refreshHistory:async()=>{calls.push('history');return failed!=='history';},
      api:async(url,body)=>calls.push([url,body.token])});
    vm.runInContext(source,context);await context.confirmFrontendPatch();
    assert.equal(calls.some(call=>Array.isArray(call)),!failed,`${failed||'successful'} startup acknowledgement`);
  }
});
