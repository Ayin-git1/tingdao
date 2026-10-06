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
  includes(/\.tn-card\{[^}]*background:var\(--note\)/);
  includes(/\.tn-editor\{[^}]*color:var\(--noteink\)/);
  includes(/html\[data-appearance="dark"\] \.tn-menu\{[^}]*background:var\(--material-rest-background\)/);
});

test('note Enter saves and Shift+Enter stays available for a newline', () => {
  includes(/transcriptNoteText'\)\.addEventListener\('keydown',e=>\{if\(e\.key==='Enter'&&!e\.shiftKey\)\{e\.preventDefault\(\);\$\('transcriptNoteSave'\)\.click\(\);\}\}\)/);
  includes(/id="transcriptNoteText"[^>]*contenteditable="true"[^>]*role="textbox" aria-multiline="true"/);
  assert.doesNotMatch(html, /可以调整，不能晚于录音结束|便签会按时间写入逐字稿/);
});

test('composer keeps the selected row timestamp in a hidden field', () => {
  includes(/id="transcriptNoteTime" type="hidden"/);
  includes(/transcriptNoteTime'\)\.value=fmt\(Math\.min\(Number\(transcriptNoteOriginal\?\.t\?\?transcriptNoteTargetTime\),transcriptNoteDuration\)\)/);
});

test('right-clicking a note offers edit and delete and edit reuses the paper composer', () => {
  includes(/id="transcriptNoteEdit"/);
  includes(/id="transcriptNoteDelete"/);
  includes(/openTranscriptNote\(transcriptNoteTargetTime,transcriptNoteTargetIndex\)/);
  includes(/transcriptNoteEditingIndex!==null[\s\S]*?api\('\/api\/timeline_note_update'/);
  includes(/api\('\/api\/timeline_note_delete'/);
  includes(/const images=\(note\.content\|\|\[\]\)\.filter\(node=>node\.type==='image'\)/);
  includes(/expected_t:note\.t,expected_text:note\.text/);
  includes(/row\.classList\.contains\('note'\)/);
});

test('note mutations rerender note rows and outside pointer closes both surfaces', () => {
  includes(/function renderTimelineNotes\(\)[\s\S]*?querySelectorAll\('\.seg\.note,\.transcript-note-card,\.transcript-note-image,\.transcript-image-divider'\)/);
  includes(/function renderTimelineNotes\(\)[\s\S]*?createTranscriptNoteImage\(/);
  assert.doesNotMatch(html, /renderTranscriptCanvasImages\(\)/);
  includes(/document\.addEventListener\('pointerdown',[\s\S]*?closeTranscriptNote\(\)[\s\S]*?hideTranscriptNoteMenu\(\)/);
});
