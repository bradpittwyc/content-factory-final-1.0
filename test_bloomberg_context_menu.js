const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('bloomberg_main_extension/worker.js', 'utf8');

async function testCase(kind, saved = true, busy = false) {
  const menus = [], storage = {}, removed = [], activated = [], requests = [];
  const article = 'https://www.bloomberg.com/news/articles/2026-10-07/example';
  let created = null;
  const context = vm.createContext({
    URL, Date, AbortSignal, setTimeout: callback => callback(),
    chrome: {
      storage: { local: { get: async () => ({ autoTask: null }), set: async values => Object.assign(storage, values) } },
      contextMenus: { removeAll: callback => { menus.length = 0; callback(); }, create: menu => menus.push(menu), onClicked: { addListener() {} } },
      alarms: { get: async () => ({}), onAlarm: { addListener() {} } },
      runtime: { onMessage: { addListener() {} }, onInstalled: { addListener() {} }, onStartup: { addListener() {} } },
      tabs: {
        create: async options => { assert.equal(options.active, false); created = { ...options, id: 2, status: 'complete' }; return created; },
        get: async () => created,
        remove: async id => removed.push(id),
        update: async (id, values) => activated.push({ id, ...values }),
        onUpdated: { addListener() {} }, onRemoved: { addListener() {} }
      },
      scripting: { executeScript: async ({ func }) => func.name === 'extractArticle' ? [{ result: { url: article, title: 'Article', paragraphs: ['Body'] } }] : [] }
    },
    fetch: async (url, options) => {
      requests.push({ url, capture: JSON.parse(options.body) });
      return { ok: true, json: async () => saved ? { saved: true, title: 'Article', paragraph_count: 10, word_count: 457 } : { saved: false, status: 'subscription_gate' } };
    }
  });
  vm.runInContext(source, context);
  vm.runInContext('installCaptureMenus(); installCaptureMenus()', context);
  assert.equal(menus.length, 2, 'Reload must not duplicate menu entries');
  assert.ok(menus[0].documentUrlPatterns.every(pattern => pattern.startsWith('https://www.bloomberg.com/')));
  assert.ok(menus[1].targetUrlPatterns.every(pattern => pattern.startsWith('https://www.bloomberg.com/')));
  if (busy) vm.runInContext('running = true', context);
  context.input = { menuItemId: kind === 'link' ? 'bloomberg-save-link' : 'bloomberg-save-page', linkUrl: article + '?tracking=1' };
  context.tab = { id: 1, url: article };
  await vm.runInContext('captureFromContext(input, tab)', context);
  if (busy) {
    assert.equal(requests.length, 0);
    assert.equal(vm.runInContext('running', context), true);
    assert.match(storage.captureStatus, /已有采集任务/);
  } else {
    assert.equal(requests.length, 1);
    assert.equal(requests[0].capture.url, article);
    assert.match(storage.captureStatus, saved ? /已入库/ : /未入库/);
    if (kind === 'page') assert.equal(created, null);
    if (kind === 'link' && saved) assert.deepEqual(removed, [2]);
    if (kind === 'link' && !saved) {
      assert.deepEqual(removed, []);
      assert.equal(activated[0].active, true);
    }
  }
}

(async () => {
  await testCase('page');
  await testCase('link');
  await testCase('link', false);
  await testCase('page', true, true);
  console.log('Context-menu capture: 4 scenarios passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
