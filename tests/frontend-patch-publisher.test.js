const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {spawnSync}=require('node:child_process');
const crypto=require('node:crypto');
const tool=path.resolve('tools/frontend-patch.cjs');

test('publisher makes authenticated assets and refuses accidental key replacement',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'tingdao-publisher-'));
  const run=(...args)=>spawnSync(process.execPath,[tool,...args],{encoding:'utf8'});
  try{
    const key=path.join(dir,'private.pem'),pub=path.join(dir,'public.hex');
    assert.equal(run('keygen',key,pub).status,0);
    const before=fs.readFileSync(key);
    assert.notEqual(run('keygen',key,pub).status,0);
    assert.deepEqual(fs.readFileSync(key),before);
    if(process.platform!=='win32')assert.equal(fs.statSync(key).mode&0o777,0o600);
    const html=path.join(dir,'index.html');fs.writeFileSync(html,'<html>patch</html>');
    const out=path.join(dir,'out');
    const args=['build','--key',key,'--public-key',pub,'--base-version','3.1.9','--revision','1','--html',html,'--out',out];
    assert.equal(run(...args).status,0);
    const raw=fs.readFileSync(path.join(out,'tingdao-patch.json'));
    const manifest=JSON.parse(raw);
    assert.equal(manifest.base_version,'3.1.9');assert.equal(manifest.revision,1);
    const page=fs.readFileSync(path.join(out,manifest.asset));
    assert.equal(manifest.sha256,crypto.createHash('sha256').update(page).digest('hex'));
    const signature=fs.readFileSync(path.join(out,'tingdao-patch.sig'));
    assert.equal(crypto.verify(null,raw,crypto.createPublicKey(fs.readFileSync(key)),signature),true);
    assert.notEqual(run(...args).status,0,'do not overwrite release artifacts');
    assert.equal(run('build','--key',key,'--public-key',pub,'--base-version','3.1.9','--revision','2','--rollback','--out',path.join(dir,'rollback')).status,0);
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir,'rollback','tingdao-patch.json'))).action,'builtin');
    for(const revision of ['0','-1','1.2','1bad']){
      const bad=[...args];bad[bad.indexOf('--revision')+1]=revision;
      assert.notEqual(run(...bad).status,0);
    }
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
