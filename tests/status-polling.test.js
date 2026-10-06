const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync('index.html', 'utf8');
const apiStart = html.indexOf('async function api(path, body){');
const apiSource = html.slice(apiStart, html.indexOf('function defaultName()', apiStart));
const pollFunctionStart = html.indexOf('async function pollStatus(){');
const guardStart = html.lastIndexOf('let statusPollInFlight = false;', pollFunctionStart);
const pollSource = html.slice(guardStart < 0 ? pollFunctionStart : guardStart,
  html.indexOf('\n/* ---- 流式字幕:', pollFunctionStart));

function harness() {
  const requests = [], applied = [];
  const context = vm.createContext({
    fetch(path, options) {
      let resolve, reject;
      const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
      requests.push({path, options, resolve, reject});
      return promise;
    },
    applyStatus(status) { applied.push(status); },
  });
  vm.runInContext(apiSource + pollSource, context);
  return {context, requests, applied};
}

function respond(request, value = {state:'recording'}) {
  request.resolve({json:async () => value});
}

test('slow status requests do not overlap or apply the same poll repeatedly', async () => {
  const {context, requests, applied} = harness();
  const first = context.pollStatus();
  const overlapping = Array.from({length:100}, () => context.pollStatus());
  assert.equal(requests.length, 1);
  respond(requests[0]);
  await Promise.all([first, ...overlapping]);
  assert.equal(applied.length, 1);
  const next = context.pollStatus();
  assert.equal(requests.length, 2);
  respond(requests[1], {state:'paused'});
  await next;
  assert.equal(applied[1].state, 'paused');
});

test('network rejection releases protection for the next poll', async () => {
  const {context, requests, applied} = harness();
  const first = context.pollStatus();
  requests[0].reject(new Error('network failed'));
  await first;
  assert.equal(applied.length, 0);
  const next = context.pollStatus();
  assert.equal(requests.length, 2);
  respond(requests[1]);
  await next;
  assert.equal(applied.length, 1);
});

test('JSON parsing failure releases protection', async () => {
  const {context, requests} = harness();
  const first = context.pollStatus();
  requests[0].resolve({json:async () => { throw new Error('invalid JSON'); }});
  await first;
  const next = context.pollStatus();
  assert.equal(requests.length, 2);
  respond(requests[1]);
  await next;
});

test('UI application failure releases poll protection', async () => {
  const {context, requests} = harness();
  context.applyStatus = () => { throw new Error('UI failed'); };
  const first = context.pollStatus();
  respond(requests[0]);
  await first;
  const next = context.pollStatus();
  assert.equal(requests.length, 2);
  respond(requests[1]);
  await next;
});

test('startup and stop/job status consumers share an in-flight request', async () => {
  const {context, requests, applied} = harness();
  const shared = [context.fetchStatus(), context.fetchStatus()];
  const poll = context.pollStatus();
  assert.equal(requests.length, 1);
  const status = {state:'idle', seq:123, jobs:{}};
  respond(requests[0], status);
  const result = await Promise.all([...shared, poll]);
  assert.equal(result[0], status);
  assert.equal(result[1], status);
  assert.equal(applied.length, 1);
});

test('all status API consumers use the shared fetch, while cadence stays unchanged', () => {
  assert.equal((html.match(/api\('\/api\/status'\)/g) || []).length, 1);
  assert.match(html, /setInterval\(\(\)=>\{ if\(state === 'recording' && view === null\) pollStatus\(\); \}, 180\)/);
  assert.match(html, /\}, 900\);/);
  assert.match(html, /fetchStatus\(\)\.then\(st=>\{ applyStatus\(st\); lastSeq = st.seq \|\| 0; seeded = true;/);
  assert.match(html, /const st = await fetchStatus\(\);/);
});
