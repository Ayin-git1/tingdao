const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const language = html.slice(html.indexOf('const LANGS ='), html.indexOf('/* ---- 麦克风输入源:'));

function setup(saved, failSave = false) {
  const elements = {fldLang:{}, dvLang:{}};
  const writes = [], messages = [];
  const context = vm.createContext({
    $: id => elements[id], PICK:{}, pickOpen(){}, api: async () => saved,
    async savePersonalSetting(key, value) {
      if(failSave) throw Error('failed');
      writes.push({key, value});
    },
    toast: message => messages.push(message),
  });
  vm.runInContext(language, context);
  return {context, elements, writes, messages};
}

test('four choices are present and simplified Chinese is default', async () => {
  const {context, elements} = setup({});
  await vm.runInContext('languageReady', context);
  assert.equal(context.PICK.lang.cur(), 'zh');
  assert.equal(elements.dvLang.textContent, '简体中文');
  assert.deepEqual(Array.from(context.PICK.lang.opts(), item => item.t),
                   ['简体中文', '繁体中文', '英语', '自动识别']);
});

test('saved language is restored and each selection is persisted', async () => {
  const {context, elements, writes} = setup({asr_language:'zh-tw'});
  await vm.runInContext('languageReady', context);
  assert.equal(context.PICK.lang.cur(), 'zh-tw');
  assert.equal(elements.dvLang.textContent, '繁体中文');
  for(const value of ['en', 'auto', 'zh']) {
    await context.PICK.lang.onPick(value);
    assert.equal(context.PICK.lang.cur(), value);
    assert.equal(writes.at(-1).key, 'asr_language');
    assert.equal(writes.at(-1).value, value);
  }
});

test('failed save retains the previous language', async () => {
  const {context, messages} = setup({asr_language:'en'}, true);
  await context.PICK.lang.onPick('zh-tw');
  assert.equal(context.PICK.lang.cur(), 'en');
  assert.equal(messages.length, 1);
});
