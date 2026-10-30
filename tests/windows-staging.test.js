const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const stage = fs.readFileSync('tauri-shell/stage_windows.js', 'utf8');

test('clean Windows staging creates the embedded page and all source resources', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tingdao-stage-test-'));
  try {
    const shell = path.join(root, 'tauri-shell');
    fs.mkdirSync(shell);
    for (const name of ['app.py', 'index.html', 'whisper_worker.py', 'whisper_worker_windows.py'])
      fs.writeFileSync(path.join(root, name), name);
    fs.mkdirSync(path.join(root, 'assets'));
    fs.mkdirSync(path.join(root, 'sounds'));
    fs.writeFileSync(path.join(root, 'assets/material-preview-lakeside.png'), 'preview');
    fs.mkdirSync(path.join(root, 'assets/demo'));
    fs.writeFileSync(path.join(root, 'assets/demo/demo-session.json'), 'demo');
    fs.writeFileSync(path.join(root, 'sounds/test.mp3'), 'sound');
    fs.mkdirSync(path.join(root, 'opencc/dictionary'), {recursive:true});
    fs.writeFileSync(path.join(root, 'opencc/dictionary/TSCharacters.txt'), 'dict');
    // Execute the source staging phase without the independent FFmpeg network download.
    new Function('require', '__dirname', stage.split('// 固定 LGPL')[0])(require, shell);
    const placeholder = fs.readFileSync(path.join(shell, 'dist/index.html'), 'utf8');
    assert.ok(placeholder.includes('background:transparent'));
    const resources = JSON.parse(fs.readFileSync('tauri-shell/tauri.windows.conf.json', 'utf8')).bundle.resources;
    for (const resource of resources.filter(r => !r.endsWith('/ffmpeg/')))
      assert.ok(fs.existsSync(path.join(shell, resource)), `missing staged resource ${resource}`);
    const staged = fs.readdirSync(path.join(shell, 'program-windows')).map(name =>
      `program-windows/${name}${fs.statSync(path.join(shell, 'program-windows', name)).isDirectory() ? '/' : ''}`);
    assert.deepEqual(staged.sort(), resources.filter(r => !r.endsWith('/ffmpeg/')).sort());
    assert.equal(fs.readFileSync(path.join(shell, 'program-windows/assets/material-preview-lakeside.png'), 'utf8'), 'preview');
    assert.equal(fs.readFileSync(path.join(shell, 'program-windows/opencc/dictionary/TSCharacters.txt'), 'utf8'), 'dict');
    assert.equal(fs.readFileSync(path.join(shell, 'program-windows/assets/demo/demo-session.json'), 'utf8'), 'demo');
  } finally { fs.rmSync(root, {recursive:true, force:true}); }
});

test('Windows build stages first and release versions agree', () => {
  const pkg = JSON.parse(fs.readFileSync('tauri-shell/package.json', 'utf8'));
  const config = JSON.parse(fs.readFileSync('tauri-shell/tauri.conf.json', 'utf8'));
  const cargo = fs.readFileSync('tauri-shell/Cargo.toml', 'utf8');
  assert.ok(pkg.scripts['build:windows'].startsWith('npm run stage:windows &&'));
  assert.equal(pkg.version, config.version);
  assert.equal(cargo.match(/^version = "([^"]+)"/m)[1], config.version);
});

test('both installers ship the bundled opencc next to app.py', () => {
  const mac = JSON.parse(fs.readFileSync('tauri-shell/tauri.conf.json', 'utf8')).bundle.resources;
  assert.equal(mac['../opencc/'], 'program/opencc/');
  assert.ok(fs.existsSync('opencc/dictionary/TSCharacters.txt'));
  const win = JSON.parse(fs.readFileSync('tauri-shell/tauri.windows.conf.json', 'utf8')).bundle.resources;
  assert.ok(win.includes('program-windows/opencc/'));
});
