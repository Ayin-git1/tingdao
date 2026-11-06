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
    /html\[data-appearance="dark"\] \.setclose:hover\s*\{\s*background:color-mix\(in srgb, #5a5c63 60%, transparent\); border-color:#6a6c73; color:#fff;\s*\}/,
  );
});

test('transcript outline level-2 items are black in light mode and readable in dark mode', () => {
  assert.match(
    html,
    /\.transcript-outline-item\.level-2\s*\{\s*padding-left:28px; color:#000;\s*\}/,
  );
  assert.match(
    html,
    /html\[data-appearance="dark"\] \.transcript-outline-item\.level-2\s*\{\s*color:var\(--txt\);\s*\}/,
  );
});

test('dark appearance softens theme-filled primary buttons without touching the light rules', () => {
  const fs = require('node:fs');
  const source = fs.readFileSync('index.html', 'utf8');
  const rule = source.match(/html\[data-appearance="dark"\] :is\(([^)]*\.gr-primary[^)]*)\)\{([^}]*)\}/);
  assert.ok(rule, 'dark primary button override exists');
  for (const name of ['.gr-primary', '.rv-primary', '.rv-confirm', '.uc-go', '.au-go']) assert.ok(rule[1].includes(name), name);
  assert.match(rule[2], /background:var\(--g-tint\)/);
  assert.match(rule[2], /color:var\(--theme-text\)!important/);
  assert.match(source, /\.gr-shell \.gr-primary\{[^}]*background:var\(--gd\);color:white/);
  assert.match(source, /\.rv-primary\{[^}]*background:var\(--gd\);color:#fff!important/);
});
