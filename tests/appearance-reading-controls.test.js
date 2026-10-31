const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');

function functionCode(name) {
  const start = html.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `${name} 尚未实现`);
  return html.slice(start, html.indexOf('\n}', start) + 2);
}

function fakeDom() {
  const el = (props = {}) => ({ hidden: false, disabled: false, textContent: '', attrs: {}, events: [],
    setAttribute(k, v) { this.attrs[k] = v; }, dispatchEvent(e) { this.events.push(e.type); }, ...props });
  const presets = ['1.5', '1.75', '2'].map(v => el({ dataset: { v } }));
  const elements = {
    transcriptFontSize: el({ value: 16, min: '14', max: '18' }),
    transcriptLineHeight: el({ value: 1.75 }),
    transcriptFontSizeValue: el(), transcriptLineHeightValue: el(), transcriptLineHeightCustom: el(),
    transcriptFontSmaller: el(), transcriptFontLarger: el(),
    transcriptLineHeightPresets: el({ querySelectorAll: () => presets }),
  };
  const ctx = { $: id => elements[id], Math, Event: class { constructor(type) { this.type = type; } },
    document: { documentElement: { style: { setProperty() {} } } } };
  vm.createContext(ctx);
  vm.runInContext(functionCode('applyTranscriptReading') + functionCode('nudgeReadingRange'), ctx);
  return { ctx, elements, presets };
}

test('settings appearance tab keeps the original controls inside a grouped list', () => {
  const section = html.slice(html.indexOf('id="sec-appearance"'), html.indexOf('id="sec-sound"'));
  for (const id of ['setAppearance', 'themePresets', 'themeCustomTrigger', 'themePopover', 'setMaterialMode',
    'materialAdjustments', 'setSummaryBackground', 'transcriptFontSize', 'transcriptLineHeight', 'setUsername'])
    assert.match(section, new RegExp(`id="${id}"`), `${id} 必须保留`);
  assert.match(section, /class="pref-box"/);
  assert.match(section, /id="transcriptFontSmaller"/);
  assert.match(section, /id="transcriptLineHeightPresets"/);
});

test('font stepper disables at the range ends', () => {
  const { ctx, elements } = fakeDom();
  ctx.applyTranscriptReading(14, 1.75);
  assert.equal(elements.transcriptFontSmaller.disabled, true);
  assert.equal(elements.transcriptFontLarger.disabled, false);
  ctx.applyTranscriptReading(18, 1.75);
  assert.equal(elements.transcriptFontLarger.disabled, true);
  assert.equal(elements.transcriptFontSizeValue.textContent, '18 px');
});

test('line height presets mark only an exact match and reveal custom values', () => {
  const { ctx, elements, presets } = fakeDom();
  ctx.applyTranscriptReading(16, 2);
  assert.deepEqual(presets.map(b => b.attrs['aria-pressed']), ['false', 'false', 'true']);
  assert.equal(elements.transcriptLineHeightCustom.hidden, true);
  ctx.applyTranscriptReading(16, 1.9);
  assert.deepEqual(presets.map(b => b.attrs['aria-pressed']), ['false', 'false', 'false']);
  assert.equal(elements.transcriptLineHeightCustom.hidden, false);
  assert.equal(elements.transcriptLineHeightValue.textContent, '1.90');
});

test('stepper and presets drive the original range so saving stays unchanged', () => {
  const { ctx, elements } = fakeDom();
  ctx.nudgeReadingRange(elements.transcriptFontSize, 17);
  assert.equal(elements.transcriptFontSize.value, 17);
  assert.deepEqual(elements.transcriptFontSize.events, ['input', 'change']);
  ctx.nudgeReadingRange(elements.transcriptFontSize, 17);
  assert.deepEqual(elements.transcriptFontSize.events, ['input', 'change'], '同值不重复保存');
});
