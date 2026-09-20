const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

test('dark theme gives the status hanger a visible cool-gray rope', () => {
  assert.match(
    html,
    /html\[data-appearance="dark"\] \.hang \.rope\s*\{\s*background:linear-gradient\(to bottom, rgba\(181,183,189,\.42\), rgba\(181,183,189,\.24\)\);\s*\}/,
  );
});

test('dark theme keeps the settings close X light on a medium hover surface', () => {
  assert.match(
    html,
    /html\[data-appearance="dark"\] \.setclose:hover\s*\{\s*background:#5a5c63; border-color:#6a6c73; color:#fff;\s*\}/,
  );
});
