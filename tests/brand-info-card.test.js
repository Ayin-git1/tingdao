const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const includes = pattern => assert.ok(pattern.test(html), `missing brand info card wiring: ${pattern}`);

test('brand info card exposes the injected app version and the project repository', () => {
  includes(/id="brandInfo"/);
  includes(/id="brandVersion">__TINGDAO_VERSION__</);
  includes(/href="https:\/\/github\.com\/Ayin-git1\/tingdao"/);
});

test('brand info card waits 1.2 seconds before opening and closes when its hover region is left', () => {
  includes(/function scheduleBrandInfo\(\)[\s\S]*?setTimeout\(openBrandInfo,\s*1200\)/);
  includes(/brandInfo\.addEventListener\('pointerenter',\s*scheduleBrandInfo\)/);
  includes(/brandInfo\.addEventListener\('pointerleave',\s*closeBrandInfo\)/);
  includes(/function closeBrandInfo\(\)[\s\S]*?clearTimeout\(brandInfoTimer\)[\s\S]*?brandInfoCard\.hidden\s*=\s*true/);
});

test('brand info card is available to keyboard users without a hover delay', () => {
  includes(/brandInfo\.addEventListener\('focusin',\s*openBrandInfo\)/);
  includes(/brandInfo\.addEventListener\('focusout',\s*e=>\{if\(!brandInfo\.contains\(e\.relatedTarget\)\)\s*closeBrandInfo\(\);\}\)/);
});

test('repository address stays on one line and clips inside the card', () => {
  includes(/\.brand-repository>span:first-child\{[^}]*flex:none[^}]*white-space:nowrap/);
  includes(/\.brand-repository>span:last-child\{[^}]*min-width:0[^}]*white-space:nowrap[^}]*overflow:hidden/);
});
