const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function cssRule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = html.match(new RegExp(`${escaped}\\{[^}]*\\}`));
  assert.ok(match, `${selector} CSS rule should exist`);
  return match[0];
}

function cssRuleMatching(pattern, label) {
  const match = html.match(pattern);
  assert.ok(match, `${label} CSS rule should exist`);
  return match[0];
}

test('audio material exposes fixed rest and expanded tokens in both appearances', () => {
  const root = cssRuleMatching(/:root\{[\s\S]*?--material-rest-background:[\s\S]*?--material-expanded-shadow:[\s\S]*?\}/,
    'light material token block');
  for (const token of [
    '--material-shadow-level-1', '--material-shadow-level-2', '--material-shadow-level-3',
    '--material-rest-background', '--material-rest-backdrop-filter',
    '--material-rest-border', '--material-rest-shadow',
    '--material-expanded-background', '--material-expanded-backdrop-filter',
    '--material-expanded-border', '--material-expanded-shadow',
  ]) {
    assert.match(root, new RegExp(`${token}:`));
  }

  const dark = cssRuleMatching(/html\[data-appearance="dark"\] \{[\s\S]*?--material-rest-background:[\s\S]*?\}/,
    'dark material token block');
  for (const token of [
    '--material-shadow-level-1', '--material-shadow-level-2', '--material-shadow-level-3',
    '--material-rest-background', '--material-rest-backdrop-filter',
    '--material-rest-border', '--material-rest-shadow',
    '--material-expanded-background', '--material-expanded-backdrop-filter',
    '--material-expanded-border', '--material-expanded-shadow',
  ]) {
    assert.match(dark, new RegExp(`${token}:`));
  }
});

test('audio bar and recording pill consume separate rest and expanded material tokens', () => {
  const audioRest = cssRule('.audiobar');
  assert.match(audioRest, /background:var\(--material-rest-background\)/);
  assert.match(audioRest, /backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(audioRest, /-webkit-backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(audioRest, /border:1\.5px solid var\(--material-rest-border\)/);
  assert.match(audioRest, /box-shadow:var\(--material-shadow-level-3\)/);

  const audioExpanded = cssRuleMatching(/\.audiobar:hover,\.audiobar:has\(:focus-visible\)\{[^}]*\}/,
    'expanded audio bar');
  assert.match(audioExpanded, /background:var\(--material-expanded-background\)/);
  assert.match(audioExpanded, /border-color:var\(--material-expanded-border\)/);
  assert.match(audioExpanded, /backdrop-filter:var\(--material-expanded-backdrop-filter\)/);
  assert.match(audioExpanded, /-webkit-backdrop-filter:var\(--material-expanded-backdrop-filter\)/);
  assert.match(audioExpanded, /box-shadow:var\(--material-expanded-shadow\)/);

  const recordingRest = cssRuleMatching(/\.recpill:not\(\.rec\)\{[^}]*\}/, 'rest recording pill');
  assert.match(recordingRest, /background:var\(--material-rest-background\)/);
  assert.match(recordingRest, /backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(recordingRest, /box-shadow:var\(--material-shadow-level-3\)/);

  const recordingExpanded = cssRuleMatching(/\.recpill:not\(\.rec\):is\(:hover,:focus-visible\)\{[^}]*\}/,
    'expanded recording pill');
  assert.match(recordingExpanded, /backdrop-filter:var\(--material-expanded-backdrop-filter\)/);
  assert.match(recordingExpanded, /-webkit-backdrop-filter:var\(--material-expanded-backdrop-filter\)/);
  assert.match(recordingExpanded, /box-shadow:var\(--material-shadow-level-3\)/);
});

test('ordinary project cards use the shared material while the new card stays separate', () => {
  const card = cssRule('.rc:not(.new)');
  assert.match(card, /background:var\(--material-rest-background\)/);
  assert.match(card, /border-color:var\(--material-rest-border\)/);
  assert.match(card, /backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(card, /-webkit-backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(card, /box-shadow:var\(--material-rest-shadow\)/);

  const hover = cssRule('.rc:not(.new):hover');
  assert.match(hover, /background:var\(--material-expanded-background\)/);
  assert.match(hover, /border-color:var\(--material-expanded-border\)/);
  assert.match(hover, /backdrop-filter:var\(--material-expanded-backdrop-filter\)/);
  assert.match(hover, /box-shadow:var\(--material-expanded-shadow\)/);

  const newCard = cssRule('.rc.new');
  assert.match(newCard, /border-style:dashed/);
  assert.match(newCard, /border-color:var\(--g\)/);
});

test('neutral controls and dropdown surfaces use the rest material', () => {
  const surfaces = [
    '.sidebar-tab-slider', '.palette', '.tp', '.findbar', '.volpop',
    '.hwpop', '.spkpop', '.cloudpop', '.sortpop', '.srcmenu', '.hmenu', '.mvpop',
    '.tplpop', '.gpop', '.tagpal', '.theme-popover', '.tn-menu', '.tn-image-menu',
  ];

  for (const selector of surfaces) {
    const rule = cssRule(selector);
    assert.match(rule, /background:var\(--material-rest-background\)/, `${selector} should use rest background`);
    assert.match(rule, /backdrop-filter:var\(--material-rest-backdrop-filter\)/,
      `${selector} should use rest blur`);
    assert.match(rule, /-webkit-backdrop-filter:var\(--material-rest-backdrop-filter\)/,
      `${selector} should use WebKit rest blur`);
  }

  const selectedHistoryCard = cssRuleMatching(/body:not\(\.batchmode\) \.hitem\.on,body:not\(\.batchmode\) \.hitem\.on:hover\{[^}]*\}/,
    'selected history card');
  assert.match(selectedHistoryCard, /background:var\(--material-rest-background\)/);
  assert.match(selectedHistoryCard, /backdrop-filter:var\(--material-rest-backdrop-filter\)/);

  const sidebarPeek = cssRuleMatching(/body\.sidehide\.side-peek \.sidebar::before\{[^}]*\}/,
    'sidebar peek material');
  assert.match(sidebarPeek, /background:var\(--material-rest-background\)/);
  assert.match(sidebarPeek, /backdrop-filter:var\(--material-rest-backdrop-filter\)/);
});

test('sidebar tab track stays transparent while the selected tab keeps material', () => {
  const track = cssRule('.sidebar-tabs');
  assert.match(track, /background:transparent/);
  assert.match(track, /backdrop-filter:none/);
  assert.match(track, /-webkit-backdrop-filter:none/);

  const selectedTab = cssRule('.sidebar-tab-slider');
  assert.match(selectedTab, /background:var\(--material-rest-background\)/);
  assert.match(selectedTab, /backdrop-filter:var\(--material-rest-backdrop-filter\)/);
  assert.match(selectedTab, /-webkit-backdrop-filter:var\(--material-rest-backdrop-filter\)/);
});
