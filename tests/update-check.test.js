const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const includes = pattern => assert.ok(pattern.test(html), `missing update/about wiring: ${pattern}`);

test('settings has an About tab grouped on its own', () => {
  includes(/data-t="about"[^>]*>关于<i class="nav-dot" id="aboutDot" hidden/);
  includes(/SET_GROUPS = \[[^\n]*\['about'\]\];/);
  includes(/id="sec-about"/);
  includes(/if\(key==='about'\)openAboutSection\(\);/);
});

test('startup check respects the auto-check setting and waits for the first screen', () => {
  includes(/updateAuto = st\.update_auto !== false;/);
  includes(/if\(updateAuto\) setTimeout\(\(\)=> checkForUpdate\(false\), 4000\);/);
});

test('update card hides for skipped versions and for "later" within this run', () => {
  includes(/const updatePending = \(\)=> !!\(updateInfo\?\.ok && updateInfo\.available && updateInfo\.latest !== updateSkip\);/);
  includes(/show = updatePending\(\) && !updateLater/);
  includes(/savePersonalSetting\('update_skip', updateSkip\)/);
});

test('download buttons point at the platform installer, falling back to the release page', () => {
  includes(/\$\('ucGo'\)\.href = updateInfo\.download_url \|\| updateInfo\.url;/);
  includes(/\$\('auGo'\)\.href = info\.download_url \|\| info\.url;/);
});

test('details button stops the click before the outside-click handler closes settings', () => {
  includes(/\$\('ucMore'\)\.addEventListener\('click', e=>\{\s*e\.stopPropagation\(\);/);
});

test('release notes are rendered through the escaping markdown renderer', () => {
  includes(/\$\('auNotes'\)\.innerHTML = md\(plainReleaseMd\(info\.notes\)\)/);
});
