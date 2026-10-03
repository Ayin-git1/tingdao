const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const includes = pattern => assert.ok(pattern.test(html), `missing image-note wiring: ${pattern}`);

test('paper note uses a contenteditable image-aware editor and image picker', () => {
  includes(/id="transcriptNoteText"[^>]*contenteditable="true"/);
  includes(/id="transcriptNoteImageButton"/);
  includes(/id="transcriptNoteImageInput"[^>]*type="file"[^>]*accept="image\/png,image\/jpeg,image\/gif,image\/webp"[^>]*multiple/);
  includes(/class="tn-editor"/);
});

test('structured note content renders safe text and non-editable image nodes', () => {
  includes(/function renderTranscriptNoteContent\(content,legacyText\)/);
  includes(/function serializeTranscriptNoteContent\(\)/);
  includes(/contentEditable='false'/);
  includes(/type==='text'/);
  includes(/type==='image'/);
  includes(/note\.content\|\|\[\]/);
});

test('selected files are inserted in order and saved as content plus assets', () => {
  includes(/function insertTranscriptNoteFiles\(files\)/);
  includes(/Promise\.all\(/);
  includes(/assets\.push\(/);
  includes(/content:serialized\.content/);
  includes(/assets:serialized\.assets/);
  includes(/api\('\/api\/timeline_note'/);
  includes(/api\('\/api\/timeline_note_update'/);
});

test('editor keeps legacy Enter save and Shift+Enter newline behavior', () => {
  includes(/transcriptNoteText'\)\.addEventListener\('keydown',[\s\S]*?e\.key==='Enter'&&!e\.shiftKey/);
  includes(/<span class="tn-hint">Enter 保存 · Shift \+ Enter 换行<\/span>/);
});
