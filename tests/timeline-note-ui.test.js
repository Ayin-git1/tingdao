const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const includes = pattern => assert.ok(pattern.test(html), `missing UI wiring: ${pattern}`);

test('completed transcript rows open the nonmodal paper note composer at their timestamp', () => {
  assert.match(html, /id="transcriptNoteLayer" hidden/);
  assert.match(html, /class="tn-card" role="dialog" aria-modal="false"/);
  assert.match(html, /addEventListener\('contextmenu',[\s\S]*?row\.dataset\.t/);
  assert.match(html, /openTranscriptNote\(transcriptNoteTargetTime\)/);
});

test('composer constrains time to the loaded recording and posts the selected timestamp', () => {
  includes(/transcriptNoteDuration\s*=\s*Math\.max\(0,Math\.floor\(Number\(view\.duration\)\|\|0\)\)/);
  includes(/Math\.min\(transcriptNoteDuration,Math\.floor\(seconds\)\)/);
  includes(/api\('\/api\/timeline_note',\{id:sid,t,text:serialized\.text,content:serialized\.content,assets:serialized\.assets\}\)/);
  includes(/view\.notes=result\.notes\|\|\[\.\.\.\(view\.notes\|\|\[\]\),result\.note\];[\s\S]*?renderTimelineNotes\(\)/);
});

test('paper note and context menu have explicit dark appearance colors', () => {
  includes(/html\[data-appearance="dark"\] \.tn-card\{[^}]*background:#363225/);
  includes(/html\[data-appearance="dark"\] \.tn-editor\{[^}]*color:#f0e3bd/);
  includes(/html\[data-appearance="dark"\] \.tn-menu\{[^}]*background:var\(--material-rest-background\)/);
});

test('note Enter saves, Shift+Enter stays available for a newline, and hint explains both', () => {
  includes(/transcriptNoteText'\)\.addEventListener\('keydown',e=>\{if\(e\.key==='Enter'&&!e\.shiftKey\)\{e\.preventDefault\(\);\$\('transcriptNoteSave'\)\.click\(\);\}\}\)/);
  includes(/<span class="tn-hint">Enter 保存 · Shift \+ Enter 换行<\/span>/);
  assert.doesNotMatch(html, /可以调整，不能晚于录音结束|便签会按时间写入逐字稿/);
});

test('time controls are labeled and hold to repeat adjustment', () => {
  includes(/>调整时间<\/label>/);
  assert.doesNotMatch(html, /id="transcriptNoteRange"/);
  includes(/function startTranscriptNoteStep\(button,delta\)[\s\S]*?setInterval\(\(\)=>stepTranscriptNoteTime\(delta\),100\)/);
  includes(/\$\('transcriptNoteMinus'\),-5\);[\s\S]*?\$\('transcriptNotePlus'\),5\)/);
});

test('right-clicking a note offers edit and delete and edit reuses the paper composer', () => {
  includes(/id="transcriptNoteEdit"/);
  includes(/id="transcriptNoteDelete"/);
  includes(/openTranscriptNote\(transcriptNoteTargetTime,transcriptNoteTargetIndex\)/);
  includes(/transcriptNoteEditingIndex!==null[\s\S]*?api\('\/api\/timeline_note_update'/);
  includes(/api\('\/api\/timeline_note_delete'/);
  includes(/confirm\('删除这条笔记吗？'\)/);
  includes(/row\.classList\.contains\('note'\)/);
});

test('note mutations rerender note rows and outside pointer closes both surfaces', () => {
  includes(/function renderTimelineNotes\(\)[\s\S]*?querySelectorAll\('\.seg\.note,\.transcript-note-card,\.transcript-note-image,\.transcript-image-divider'\)/);
  includes(/function renderTimelineNotes\(\)[\s\S]*?createTranscriptNoteImage\(/);
  assert.doesNotMatch(html, /renderTranscriptCanvasImages\(\)/);
  includes(/document\.addEventListener\('pointerdown',[\s\S]*?closeTranscriptNote\(\)[\s\S]*?hideTranscriptNoteMenu\(\)/);
});
