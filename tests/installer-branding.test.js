const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
test('Windows installer brand assets use NSIS bitmap dimensions and Chinese pages', () => {
  const cfg=JSON.parse(fs.readFileSync('tauri-shell/tauri.windows.conf.json','utf8')).bundle.windows.nsis;
  assert.deepEqual(cfg.languages,['SimpChinese']);
  for(const [key,w,h] of [['headerImage',150,57],['sidebarImage',164,314]]){
    const bytes=fs.readFileSync(path.join('tauri-shell',cfg[key]));
    assert.equal(bytes.toString('ascii',0,2),'BM');
    assert.equal(bytes.readInt32LE(18),w);assert.equal(bytes.readInt32LE(22),h);
  }
  const hook=fs.readFileSync(path.join('tauri-shell',cfg.installerHooks),'utf8');
  assert.ok(hook.includes('MUI_WELCOMEPAGE_TITLE'));assert.ok(hook.includes('MUI_FINISHPAGE_TITLE'));
  assert.ok(!hook.includes('Section '));
});
