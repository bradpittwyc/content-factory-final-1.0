// Exercise real worker steps with Chrome APIs mocked, including worker restarts.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const crypto = require('node:crypto');
const source = fs.readFileSync('bloomberg_main_extension/worker.js', 'utf8');

async function scenario(failFirstResult, invalidDiscoveries = 0) {
  const storage = {};
  const tabs = new Map();
  let id = 0, phase = 'discover', writes = 0, extractions = 0, resultCalls = 0, discoveryCalls = 0;
  const url = 'https://www.bloomberg.com/news/articles/2026-10-07/tech-example';
  function restart() {
    const context = vm.createContext({
      URL, Date, AbortSignal, crypto: crypto.webcrypto,
      setTimeout: callback => { callback(); },
      chrome: {
        contextMenus: { onClicked: { addListener() {} } },
        storage: { local: {
          get: async key => ({ [key]: storage[key] }),
          set: async values => Object.assign(storage, structuredClone(values))
        } },
        scripting: { executeScript: async ({ func }) => {
          extractions++;
          return [{ result: func.name === 'extractTechLinks' ? { links: [{ url }] } : { url, canonical_url: url } }];
        } },
        tabs: {
          create: async options => {
            assert.equal(options.active, false);
            const tab = { ...options, id: ++id, status: 'complete' };
            tabs.set(tab.id, tab);
            return tab;
          },
          get: async tabId => { if (!tabs.has(tabId)) throw Error('Closed'); return tabs.get(tabId); },
          remove: async tabId => tabs.delete(tabId),
          onUpdated: { addListener() {} }, onRemoved: { addListener() {} }
        },
        alarms: { get: async () => ({}), create: async () => {}, onAlarm: { addListener() {} } },
        runtime: { onMessage: { addListener() {} }, onInstalled: { addListener() {} }, onStartup: { addListener() {} } }
      },
      fetch: async (target, options) => {
        const action = target.split('/').pop();
        const payload = JSON.parse(options.body);
        let output;
        if (action === 'tick') {
          output = phase === 'done' ? { action: 'idle' } : { action: phase, run_id: 'run-1', url: phase === 'discover' ? 'https://www.bloomberg.com/technology' : url };
        } else if (action === 'discovery') {
          if (++discoveryCalls <= invalidDiscoveries) {
            return { ok: false, status: 422, json: async () => ({ detail: 'No supported article links found' }) };
          }
          phase = 'article';
          output = { action: 'article', run_id: 'run-1', url };
        } else if (action === 'result') {
          resultCalls++;
          if (failFirstResult && resultCalls === 1) throw Error('bridge offline');
          assert.equal(payload.run_id, 'run-1');
          if (invalidDiscoveries > 2) {
            assert.equal(payload.error, 'network_error');
            assert.match(payload.error_detail, /discovery HTTP 422.*No supported article links found/);
          } else {
            assert.equal(payload.capture.url, url);
            writes++;
          }
          phase = 'done';
          output = { saved: invalidDiscoveries <= 2, status: invalidDiscoveries > 2 ? 'network_error' : 'body_candidate' };
        } else { throw Error('Unexpected API ' + action); }
        return { ok: true, json: async () => output };
      }
    });
    vm.runInContext(source, context);
    return context;
  }
  let worker = restart();
  await vm.runInContext('automationTick()', worker);
  assert.equal(storage.autoTask.action, 'discover');
  worker = restart();
  await vm.runInContext('automationTick()', worker);
  for (let retry = 0; retry < Math.min(invalidDiscoveries, 2); retry++) {
    assert.equal(storage.autoTask.payload, undefined, 'rejected discovery must be extracted again');
    worker = restart();
    await vm.runInContext('automationTick()', worker);
  }
  if (invalidDiscoveries > 2) {
    assert.equal(resultCalls, 1);
    assert.equal(writes, 0);
    assert.equal(storage.autoTask, null);
    return;
  }
  assert.equal(storage.autoTask.action, 'article');
  assert.equal(tabs.size, 1);
  worker = restart();
  await vm.runInContext('automationTick()', worker);
  if (failFirstResult) {
    assert.ok(storage.autoTask.payload.capture);
    worker = restart();
    await vm.runInContext('automationTick()', worker);
  }
  assert.equal(writes, 1);
  assert.equal(extractions, 2 + invalidDiscoveries, 'offline recovery should replay stored payload without extracting again');
  assert.equal(storage.autoTask, null);
  assert.equal(tabs.size, 0);
  await vm.runInContext('automationTick()', worker);
  assert.equal(writes, 1);
}

(async () => {
  await scenario(false);
  await scenario(true);
  await scenario(false, 1);
  await scenario(false, 3);
  console.log('Worker restart, offline replay, discovery retry and diagnostic failure: 4 scenarios passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
