const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const includes = pattern => assert.ok(pattern.test(html), `missing note interaction wiring: ${pattern}`);

test('timeline note editor accepts image drops and shows the target indicator', () => {
  includes(/tn-drop-indicator/);
  includes(/dragover/);
  includes(/dataTransfer\.files/);
  includes(/transcriptNoteDropRange/);
  includes(/insertTranscriptNoteFiles\(files\)/);
});

test('timeline note editor pastes image clipboard files without losing text paste', () => {
  includes(/addEventListener\('paste'/);
  includes(/clipboardData\.items/);
  includes(/getAsFile\(\)/);
  includes(/if\(imageFiles\.length\)event\.preventDefault\(\)/);
});

test('image nodes expose a Word-like layout menu with supported modes', () => {
  includes(/id="transcriptNoteImageMenu"/);
  for(const layout of ['inline','square','top-bottom','behind','front'])
    includes(new RegExp(`data-layout="${layout}"`));
  includes(/contextmenu/);
  includes(/setTranscriptNoteImageLayout/);
});

test('image nodes can be resized and freely dragged, and serialization keeps geometry', () => {
  includes(/tn-resize-handle/);
  includes(/tn-delete-image/);
  includes(/startTranscriptNoteResize/);
  includes(/startTranscriptNoteMove/);
  includes(/moveTranscriptNoteFlowImage/);
  includes(/transcriptNoteUsesFreePosition/);
  includes(/displayWidth/);
  includes(/position\.mode/);
  includes(/position\.x/);
  includes(/position\.y/);
});

test('custom image dragging suppresses native image drag and keeps pointer capture', () => {
  includes(/image\.draggable\s*=\s*false/);
  includes(/addEventListener\(['"]dragstart['"][\s\S]*?preventDefault\(\)/);
  includes(/setPointerCapture\(/);
  includes(/releasePointerCapture\(/);
});

test('file drops accept known image extensions when the system omits MIME type', () => {
  includes(/function transcriptNoteImageFileIsSupported\(file\)/);
  includes(/file&&file\.type\|\|''\)\.toLowerCase\(\)/);
  includes(/file&&file\.name\|\|''\)\.toLowerCase\(\)/);
  includes(/transcriptNoteImageFileIsSupported\(file\)/);
});

test('dragover shows an indicator when WebKit exposes only file drag types', () => {
  includes(/function transcriptNoteMayContainImageFile\(dataTransfer\)/);
  includes(/dataTransfer\.types/);
  includes(/addEventListener\(['"]dragenter['"]/);
  includes(/!files\.length&&!transcriptNoteMayContainImageFile\(event\.dataTransfer\)/);
});

test('image drag target is a visible insertion placeholder, not only a caret line', () => {
  includes(/<span class="tn-drop-label">图片将在此处插入<\/span>/);
  includes(/\.tn-drop-indicator\{[^}]*min-height:44px/);
  includes(/\.tn-drop-indicator\{[^}]*border:1px dashed/);
  includes(/indicator\.style\.width=`\$\{Math\.max\(0,editorRect\.width\)\}px`/);
  includes(/indicator\.setAttribute\(['"]aria-hidden['"],['"]false['"]\)/);
});

test('Tauri native file drags reach the note editor and reuse the insertion placeholder', () => {
  includes(/tauri:\/\/drag-enter/);
  includes(/tauri:\/\/drag-over/);
  includes(/tauri:\/\/drag-drop/);
  includes(/tauri:\/\/drag-leave/);
  includes(/plugin:event\|listen/);
  includes(/target:\{kind:'Webview',label:'main'\}/);
  includes(/transcriptNoteNativeDropPaths/);
  includes(/transcriptNoteNativeClientPoint/);
  includes(/insertTranscriptNoteNativeFiles\(paths\)/);
});

test('drop and move indicators fall back to the editor end and clear outside it', () => {
  includes(/function transcriptNoteDropFallbackRange\(\)/);
  includes(/transcriptNoteDropRange\|\|transcriptNoteRangeAtPoint\([\s\S]*?\)\|\|transcriptNoteDropFallbackRange\(\)/);
  includes(/!state\.free&&!state\.range\)hideTranscriptNoteDropIndicator\(\)/);
});

test('saved timeline notes render text rows and image cards through the flow renderer', () => {
  includes(/function renderTimelineNoteText\(/);
  includes(/function createTranscriptNoteCard\(/);
  includes(/function createTranscriptNoteImage\(/);
  includes(/renderTimelineNotes\(\)/);
});

test('saved note images render in a dedicated two-column container instead of a canvas', () => {
  assert.doesNotMatch(html, /id="transcriptImageCanvas"/);
  assert.doesNotMatch(html, /function createTranscriptCanvasImage\(/);
  assert.doesNotMatch(html, /transcript-canvas-image/);
  includes(/transcript-note-card/);
  includes(/transcript-note-media/);
  includes(/border-radius:13px/);
  includes(/grid-template-columns:minmax\(0,1fr\) minmax\(180px/);
  assert.doesNotMatch(html, /div\.className\s*=\s*['"]seg note-image['"]/);
  assert.doesNotMatch(html, /querySelectorAll\(['"]\.seg\.note,\.seg\.note-image['"]\)/);
});
