const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

function copyFormatModule() {
  const html = fs.readFileSync('index.html', 'utf8');
  const start = html.indexOf('const COPY_FORMATS =');
  const end = html.indexOf('let completionSound =', start);
  assert.notEqual(start, -1, '复制格式选择器应定义统一的选项源');
  assert.notEqual(end, -1, '复制格式选择器应位于个性化设置状态附近');

  return Function(`${html.slice(start, end)}; return {COPY_FORMATS, copyFormatFor};`)();
}

test('copy format picker exposes all copy formats and falls back to plain text', () => {
  const {COPY_FORMATS, copyFormatFor} = copyFormatModule();

  assert.deepEqual(
    COPY_FORMATS.map(({value, label, detail}) => ({value, label, detail})),
    [
      {value: 'ts', label: '带时间戳', detail: 'Markdown'},
      {value: 'plain', label: '不带时间戳', detail: '纯文本'},
      {value: 'script', label: '分说话人', detail: '剧本式'},
    ],
  );
  assert.equal(copyFormatFor('missing').value, 'plain');
});
