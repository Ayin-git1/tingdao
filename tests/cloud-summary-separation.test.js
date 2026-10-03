const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const html = fs.readFileSync('index.html', 'utf8');
const backend = fs.readFileSync('app.py', 'utf8');

function blockBetween(source, start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing block: ${start}`);
  return source.slice(from, to);
}

test('summary action reuses the refine card and only enables washes while busy', () => {
  assert.match(html, /class="refine-card"[^>]*id="refineCard"|id="refineCard"[^>]*class="refine-card"/);
  assert.match(html, /id="btnGenerateSummary"/);
  assert.match(html, /\.refine-dots\{display:none;[\s\S]*?\.refine-card\.is-busy \.refine-dots\{display:flex;\}/);
  assert.match(html, /\.refine-dots\[hidden\]\{display:none;\}/);
  assert.match(html, /\.refine-card::before[\s\S]*?animation:none/);
  assert.match(html, /\.refine-card\.is-busy::before[\s\S]*?animation:refineWash/);
  assert.match(html, /\.refine-card\.is-busy::after[\s\S]*?animation:refineWash/);
});

test('summary is a separate backend job and refine no longer invokes it', () => {
  assert.match(backend, /def cloud_summary\(self, sid, regenerate=False\):/);
  assert.match(backend, /def _cloud_summary_bg\(self, d, cfg\):/);
  assert.match(backend, /if u\.path == "\/api\/cloud_summary"/);
  assert.match(backend, /APP\.cloud_summary\(\s*body\.get\("id", ""\), bool\(body\.get\("regenerate"\)\)\)/);
  assert.match(html, /api\('\/api\/cloud_summary'/);

  const refine = blockBetween(backend, '    def _cloud_refine_bg(self, d, cfg):', '    def _cloud_summary_bg');
  assert.doesNotMatch(refine, /生成摘要中|SUM_INSTR|meta\["summary"\]/);
  assert.match(refine, /meta\.pop\("summary", None\)/);
});

test('summary completion has its own event branch and does not reload as a refine job', () => {
  const finish = blockBetween(html, "if(e.type === 'refinish'){", "\n  if(e.type === 'status')");
  assert.match(finish, /e\.kind === 'summary'/);
  assert.match(finish, /AI 摘要/);
  assert.match(finish, /reloadRefined\(e\.id\)/);
});

test('summary and outline have a dedicated model control and connection probe', () => {
  assert.match(html, /id="cloudSummaryModel"/);
  assert.match(html, /id="swSummary"/);
  assert.match(html, /id="capSummary"/);
  assert.match(html, /id="btnSummaryPrompt"/);
  assert.match(html, /id="summaryPrompt"/);
  assert.match(html, /cloud_summary_model/);
  assert.match(html, /cloud_summary_think/);
  assert.match(html, /cloud_summary_prompt/);
  assert.match(html, /summary_model:\$\('cloudSummaryModel'\)\.value\.trim\(\)/);
  assert.match(html, /d\.think_summary/);
  assert.match(backend, /"summary_model": \(s\.get\("cloud_summary_model"\)/);
  assert.match(backend, /"summary_think": bool\(s\.get\("cloud_summary_think", True\)\)/);
  assert.match(backend, /"summary_prompt": \(s\.get\("cloud_summary_prompt"\)/);
  assert.match(backend, /out\["think_summary"\]/);
});
