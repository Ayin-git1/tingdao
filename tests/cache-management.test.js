const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('index.html','utf8');
const start=html.indexOf('function formatCacheSize(');
const source=html.slice(start,html.indexOf('/* ---- 方案 B 交互:',start));
function harness(api,invoke){
 const elements=Object.fromEntries(['cacheSize','cachePath','cacheLastCleared','cacheMessage','cacheClear'].map(id=>[id,{textContent:'',disabled:false}]));
 const preloads=new Map([['image',{}]]);
 const context=vm.createContext({$:id=>elements[id],api,noteImagePreloads:preloads,window:{__TAURI_INTERNALS__:invoke?{invoke}:undefined}});
 vm.runInContext(source,context);
 return {elements,preloads,context};
}
test('settings shows total size, path and last successful cleanup',async()=>{
 const {elements,context}=harness(async()=>({bytes:1536,path:'/data/.cache',last_cleared:'2026-10-05T12:00:00',errors:[]}));
 await context.loadCacheInfo();
 assert.equal(elements.cacheSize.textContent,'1.5 KB');
 assert.equal(elements.cachePath.textContent,'目录：/data/.cache');
 assert.match(elements.cacheLastCleared.textContent,/2026-10-05 12:00:00/);
});
test('cleanup busy response preserves image preloads and reenables button',async()=>{
 const {elements,preloads}=harness(async()=>({ok:false,error:'任务进行中'}));
 await elements.cacheClear.onclick();
 assert.equal(preloads.size,1);assert.equal(elements.cacheClear.disabled,false);
 assert.equal(elements.cacheMessage.textContent,'任务进行中');
});
test('successful cleanup clears preloads and calls the native browsing-data API',async()=>{
 let call;
 const {elements,preloads}=harness(async(path)=>{assert.equal(path,'/api/cache/clear');return {ok:true,bytes:0,path:'/data/.cache',errors:[]};},async(...args)=>{call=args;});
 await elements.cacheClear.onclick();
 assert.equal(preloads.size,0);assert.equal(elements.cacheSize.textContent,'0 B');
 assert.equal(call[0],'plugin:webview|clear_all_browsing_data');assert.equal(call[1].label,'main');
 assert.equal(elements.cacheMessage.textContent,'清理完成');assert.equal(elements.cacheClear.disabled,false);
});
test('partial cleanup retains error and never reports success',async()=>{
 const {elements}=harness(async()=>({ok:false,bytes:4096,path:'/data/.cache',errors:['locked']}));
 await elements.cacheClear.onclick();
 assert.equal(elements.cacheSize.textContent,'4.0 KB');assert.match(elements.cacheMessage.textContent,/未|无法/);
});
test('startup-only scheduling and nonpersistent native WebView are wired',()=>{
 const python=fs.readFileSync('app.py','utf8');
 assert.equal((python.match(/result = check_cache_on_startup\(\)/g)||[]).length,1);
 assert.match(python,/webview.start\(private_mode=True\)/);
 assert.match(fs.readFileSync('tauri-shell/src/main.rs','utf8'),/\.incognito\(true\)/);
 assert.match(html,/data-t="cache"/);assert.match(html,/'appearance','cache','key'/);
});
