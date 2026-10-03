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

test('drop and move indicators fall back to the editor end and clear outside it', () => {
  includes(/function transcriptNoteDropFallbackRange\(\)/);
  includes(/transcriptNoteDropRange\|\|transcriptNoteRangeAtPoint\([\s\S]*?\)\|\|transcriptNoteDropFallbackRange\(\)/);
  includes(/!state\.free&&!state\.range\)hideTranscriptNoteDropIndicator\(\)/);
});

test('saved timeline note rows render text and image content at the note time', () => {
  includes(/function renderTimelineNoteText\(/);
  includes(/addNoteDom\(m\.t,\s*m\.text,\s*null,\s*m\.noteIndex,\s*m\.content\)/);
  includes(/addNoteImageDom\(m\.t,\s*m\.image,\s*null,\s*m\.noteIndex\)/);
});

test('saved note images render as separate timeline rows instead of note-container children', () => {
  includes(/function renderTimelineNoteText\(/);
  includes(/function addNoteImageDom\(/);
  includes(/div\.className\s*=\s*['"]seg note-image['"]/);
  includes(/type:\s*['"]note-image['"]/);
  includes(/else\s+addNoteImageDom\(m\.t,\s*m\.image,\s*null,\s*m\.noteIndex\)/);
  includes(/querySelectorAll\(['"]\.seg\.note,\.seg\.note-image['"]\)/);
});
