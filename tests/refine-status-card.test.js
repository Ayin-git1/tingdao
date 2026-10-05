const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');

function blockBetween(start, end) {
  const from = html.indexOf(start);
  const to = html.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing block: ${start}`);
  return html.slice(from, to);
}

test('refine status uses a quiet top card with fixed copy and three loading dots', () => {
  const card = blockBetween('<div class="refine-card"', '\n    </div>');
  assert.match(card, /class="refine-card"/);
  assert.match(card, /文稿精修中/);
  assert.match(card, /完成后可生成 AI 摘要/);
  assert.match(card, /class="refine-dots"[\s\S]*?<i class="refine-dot"><\/i>[\s\S]*?<i class="refine-dot"><\/i>[\s\S]*?<i class="refine-dot"><\/i>/);
  assert.match(card, /id="btnGenerateSummary"[^>]*hidden/);
  assert.doesNotMatch(card, /refineStageTxt|精修阶段|\b\d+%/);
});

test('refine card adapts its surface to both appearances and respects reduced motion', () => {
  assert.match(html, /--refine-card:/);
  assert.match(html, /html\[data-appearance="dark"\]\s*\{[\s\S]*?--refine-card:/);
  assert.match(html, /\.refine-card\{[^}]*border:0[^}]*border-radius:var\(--radius-3\)[^}]*box-shadow:none/);
  assert.match(html, /\.refine-card::before[\s\S]*?\.refine-card::after/);
  assert.match(html, /@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?\.refine-card\.is-busy::before[\s\S]*?animation:none/);
});

test('refine jobs toggle the card without exposing stage text or percentage in it', () => {
  const update = blockBetween('function updateRefineUI(){', '\n}\n\n/* 后台停止入口');
  assert.match(update, /\$\('refinewrap'\)\.classList\.toggle\('show', showing\)/);
  assert.doesNotMatch(update, /refineStageTxt|refineStageText\(|refinePct/);
});
