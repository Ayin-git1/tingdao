const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = process.cwd();
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(root, 'app.py'), 'utf8');
const soundFiles = [
  'task_complete_warm.mp3',
  'task_complete_distant.mp3',
  'project_delete.mp3',
];

test('bundles ASCII-named notification sounds for source and Tauri runtimes', () => {
  for (const name of soundFiles) {
    const source = path.join(root, 'sounds', name);
    const bundled = path.join(root, 'tauri-shell', 'program', 'sounds', name);
    assert.ok(fs.existsSync(source), `missing source sound: ${name}`);
    assert.ok(fs.existsSync(bundled), `missing bundled sound: ${name}`);
    assert.deepEqual(fs.readFileSync(bundled), fs.readFileSync(source), `${name} must match`);
  }
});

test('serves only approved bundled notification sounds as MP3', () => {
  assert.match(app, /SOUND_FILES\s*=\s*\{/);
  assert.match(app, /elif u\.path\.startswith\("\/sound\/"\):/);
  assert.match(app, /self\.send_header\("Content-Type", "audio\/mpeg"\)/);
});

test('persists warm completion sound by default and offers both completion choices', () => {
  assert.match(html, /id="setCompletionSound"/);
  assert.match(html, /data-v="warm"[^>]*>温馨</);
  assert.match(html, /data-v="distant"[^>]*>悠远</);
  assert.match(html, /const COMPLETION_SOUNDS = \['warm', 'distant'\]/);
  assert.match(html, /completionSound = COMPLETION_SOUNDS\.includes\(st\.completion_sound\) \? st\.completion_sound : 'warm'/);
  assert.match(html, /key:'completion_sound', value:completionSound/);
});

test('plays completion and delete feedback at a quiet 14 percent volume', () => {
  assert.match(html, /function playNotificationSound\(name\)[\s\S]*audio\.volume = 0\.14/);
  assert.match(html, /playNotificationSound\(`task_complete_\$\{completionSound\}\.mp3`\)/);
  assert.match(html, /toast\('录制完成，已加载完整文稿'\);[\s\S]*playCompletionSound\(\);/);
  assert.match(html, /else if\(e\.id\)\{[\s\S]*playCompletionSound\(\);/);
  assert.match(html, /else toast\(`\$\{ok\} 个\$\{full \? '项目' : '录音'\}已移入废纸篓，可随时找回`\);[\s\S]*if\(ok\) playNotificationSound\('project_delete\.mp3'\);/);
});
