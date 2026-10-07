const BRIDGE = 'http://127.0.0.1:8011';
let running = false;
let stopRequested = false;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const setStatus = text => chrome.storage.local.set({ captureStatus: text });

// Runs in the logged-in article page. Never reads or exports cookies.
function extractArticle() {
  const visible = element => !!element.getClientRects().length;
  const pageTitle = document.title;
  const blocked = /are you a robot|access denied|just a moment|security verification/i.test(pageTitle);
  const gate = [...document.querySelectorAll('[class*="paywall"], [data-testid*="paywall"]')]
    .some(element => visible(element) && /subscribe to (read|continue)|sign in to (read|continue)|you.ve reached|subscription required/i.test(element.innerText));
  const selectors = ['article.b-article-body', '.body-copy-v2', '.body-copy', '.body-content', '.body-content-v2', '[data-component="body-content"]', '[data-testid="article-body"]', '[data-testid="body-content"]'];
  const titleNode = document.querySelector('h1');
  const firstBody = selectors.map(selector => [...document.querySelectorAll(selector)].find(visible)).find(Boolean);
  let takeawaysContainer = null, takeaways = [], takeawaysSource = '', takeawaysStatus = 'not_present';
  // Takeaways is a separate header component, outside the reporter's body.
  const headings = [...document.querySelectorAll('h2, h3, h4, strong, span, div, [role="heading"], [data-testid*="takeaway"], [data-component*="takeaway"]')]
    .filter(element => element.textContent.length < 100 && /^Takeaways\s*(?:by\s*Bloomberg\s*AI)?(?:\s*(?:Hide|Show))?$/i.test(element.textContent.trim()) && visible(element));
  for (const heading of headings) {
    if (titleNode && !(titleNode.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
    if (firstBody && !(heading.compareDocumentPosition(firstBody) & Node.DOCUMENT_POSITION_FOLLOWING) && !firstBody.contains(heading)) continue;
    takeawaysStatus = 'collapsed_or_empty';
    let container = heading.parentElement;
    for (let depth = 0; container && depth < 5; depth++, container = container.parentElement) {
      if (container === document.body || (firstBody && (container === firstBody || container.contains(firstBody)))) break;
      const items = [...container.querySelectorAll('ul li, ol li')]
        .filter(element => !element.querySelector('li'))
        .map(element => (element.innerText || element.textContent).trim()).filter(Boolean);
      if (!items.length) continue;
      takeawaysContainer = container;
      takeaways = [...new Set(items)].slice(0, 20);
      takeawaysSource = /Bloomberg\s*AI/i.test(container.textContent) ? 'Bloomberg AI' : 'Bloomberg';
      takeawaysStatus = 'captured';
      break;
    }
    if (takeaways.length) break;
  }
  let paragraphs = [], bodyBlocks = [], bodySelector = '';
  const diagnostics = [];
  bodySearch: for (const selector of selectors) {
    const nodes = [...document.querySelectorAll(selector)];
    for (const node of nodes) {
      const blocks = [...node.querySelectorAll('p, li, h2, h3, blockquote')]
        .filter(element => visible(element) && !element.querySelector('p, li, h2, h3, blockquote'))
        .filter(element => !element.closest('figure, aside, nav'))
        .filter(element => !takeawaysContainer?.contains(element))
        .map(element => {
          const text = element.innerText.trim();
          const kind = element.tagName.toLowerCase();
          const linkedText = [...element.querySelectorAll('a[href]')].map(a => a.innerText.trim()).join(' ');
          const relatedContainer = element.closest('[class*="related"], [class*="read-more"], [class*="recommend"]');
          const articleLinkOnly = ['p', 'h2', 'h3'].includes(kind) && text === linkedText &&
            [...element.querySelectorAll('a[href]')].some(a => /\/(news|opinion)\/articles\//.test(a.pathname));
          return { kind, text, is_related: !!relatedContainer || articleLinkOnly || /^(Read More|Read more|Related|Also Read)\s*:/.test(text) };
        }).filter(block => block.text);
      const candidate = blocks.filter(block => !block.is_related).map(block => block.text);
      diagnostics.push({ selector, paragraph_count: blocks.filter(b => b.kind === 'p' && !b.is_related).length, list_item_count: blocks.filter(b => b.kind === 'li').length, block_count: candidate.length });
      if (candidate.length) {
        paragraphs = candidate;
        bodyBlocks = blocks;
        bodySelector = selector;
        break bodySearch;
      }
    }
  }
  let metadata = {};
  const canonical = document.querySelector('link[rel="canonical"]')?.href || '';
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const value = JSON.parse(script.textContent);
      const nodes = Array.isArray(value) ? value : [value];
      for (const node of nodes.flatMap(item => item['@graph'] || [item])) {
        if (/Article/.test(String(node['@type'])) && !Object.keys(metadata).length) {
          const metadataUrl = node.url || node.mainEntityOfPage?.['@id'];
          if (!metadataUrl || !canonical || metadataUrl.split('?')[0] === canonical.split('?')[0]) metadata = node;
        }
      }
    } catch (_) {}
  }
  let authors = metadata.author || [];
  if (!Array.isArray(authors)) authors = [authors];
  authors = authors.map(author => typeof author === 'string' ? author : author.name).filter(Boolean);
  return {
    url: location.href, canonical_url: canonical, page_title: pageTitle,
    title: document.querySelector('h1')?.innerText.trim() || '',
    paragraphs, published_at: metadata.datePublished || document.querySelector('meta[property="article:published_time"]')?.content || null,
    authors, blocked, gated: gate, body_selector: bodySelector, diagnostics,
    body_blocks: bodyBlocks, capture_version: 2,
    takeaways, takeaways_source: takeawaysSource, takeaways_status: takeawaysStatus,
    takeaways_capture_version: 1
  };
}

function extractTechLinks() {
  const column = arguments[0] || null;
  const blocked = /are you a robot|access denied|just a moment|security verification/i.test(document.title);
  const gated = [...document.querySelectorAll('[class*="paywall"], [data-testid*="paywall"]')]
    .some(element => element.getClientRects().length && /subscribe to (read|continue)|sign in to (read|continue)|subscription required/i.test(element.innerText));
  const root = document.querySelector('main, [role="main"], #main-content') || document.body;
  const links = new Map();
  for (const anchor of root.querySelectorAll('a[href]')) {
    if (anchor.closest('header, footer, nav, aside, [role="navigation"]')) continue;
    const url = new URL(anchor.href, location.href);
    if (url.hostname !== 'www.bloomberg.com' || url.protocol !== 'https:') continue;
    if (!/^\/(news|opinion)\/(articles|newsletters)\/|^\/(news\/)?features\//.test(url.pathname)) continue;
    const normalized = url.origin + url.pathname.replace(/\/$/, '');
    const title = anchor.innerText.trim() || anchor.getAttribute('aria-label') || '';
    // A signup page is not an archive: only explicit AI Today edition links qualify.
    if (column?.id === 'ai-today' && (!url.pathname.includes('/newsletters/') ||
        !/latest edition|read (the )?latest|最新一期|ai today/i.test(title))) continue;
    if (!links.has(normalized) || (!links.get(normalized).title && title)) links.set(normalized, { url: normalized, title });
  }
  return { url: location.href, page_title: document.title, blocked, gated, links: [...links.values()] };
}

async function captureTab(tabId, column = null) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func: extractArticle });
  if (column) result.column = column;
  const response = await fetch(`${BRIDGE}/capture`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result), signal: AbortSignal.timeout(8000) });
  const output = await response.json();
  if (!response.ok) throw new Error(output.detail || '本地服务拒绝了采集结果');
  return output;
}

async function waitForLoad(tabId) {
  for (let attempt = 0; attempt < 30; attempt++) {
    if (stopRequested) return;
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === 'complete') { await delay(3000); return; }
    await delay(1000);
  }
  throw new Error('页面加载超时');
}

async function runBatch(column = null) {
  running = true;
  stopRequested = false;
  let tab;
  try {
    if (column) {
      const catalog = await (await fetch(`${BRIDGE}/columns`)).json();
      const entry = catalog.columns?.find(item => item.id === column);
      if (!entry) throw new Error('专栏未配置');
      await setStatus(`正在读取 Bloomberg ${entry.name} 栏目文章链接...`);
      tab = await chrome.tabs.create({ url: entry.url, active: true });
      await waitForLoad(tab.id);
      if (stopRequested) { await setStatus('Tech 采集已停止'); return; }
      const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extractTechLinks, args: [entry] });
      const discoveryResponse = await fetch(`${BRIDGE}/columns/${encodeURIComponent(column)}/discover`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
      const discovery = await discoveryResponse.json();
      if (!discoveryResponse.ok) throw new Error(discovery.detail || 'Tech 栏目链接读取失败');
      await setStatus(`${entry.name} 栏目发现 ${discovery.candidate_count} 个文章链接，开始试抓...`);
    }
    const response = await fetch(`${BRIDGE}/queue${column ? '?column=' + column : ''}`);
    if (!response.ok) throw new Error('本地队列不可用');
    const { articles } = await response.json();
    const queue = (column ? articles : articles.filter(a => a.url.includes('/news/articles/'))).slice(0, 10);
    let saved = 0, skipped = 0;
    for (let index = 0; index < queue.length && !stopRequested; index++) {
      await setStatus(`正在读取 ${index + 1}/${queue.length}，已保存 ${saved} 篇正文候选`);
      const previousTab = tab;
      tab = await chrome.tabs.create({ url: queue[index].url, active: true });
      if (previousTab) await chrome.tabs.remove(previousTab.id);
      await waitForLoad(tab.id);
      if (stopRequested) break;
      const result = await captureTab(tab.id, column);
      if (result.saved) saved++;
      if (result.status !== 'body_candidate') {
        if (['blocked', 'subscription_gate'].includes(result.status)) {
          await setStatus(`已暂停：${result.status}。已保存 ${saved} 篇。请在当前页面检查登录或验证提示。`);
          return;
        }
        skipped++;
        await setStatus(`跳过无法确认的正文：${result.status}。已保存 ${saved} 篇，跳过 ${skipped} 篇。`);
      }
      await delay(3000);
    }
    await setStatus(`${column === 'tech' ? 'Tech ' : ''}${stopRequested ? '已停止' : '批量结束'}，保存 ${saved} 篇正文候选，跳过 ${skipped} 篇；需检查完整性。`);
  } catch (error) {
    await setStatus(`采集停止：${error.message}。请确认本地服务已启动。`);
  } finally { running = false; }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'info') {
    sendResponse({ api_version: 5, capture_version: 2, extension_version: chrome.runtime.getManifest().version });
    return;
  } else if (message.action.startsWith('auto_')) {
    (async () => {
      try {
        const owner = await automationOwner();
        if (message.action === 'auto_status') {
          sendResponse(await automationFetch('status'));
        } else if (message.action === 'auto_enable' || message.action === 'auto_stop') {
          const result = await automationFetch('settings', { owner, enabled: message.action === 'auto_enable' });
          if (message.action === 'auto_stop') await clearAutomation(false);
          await setStatus(message.action === 'auto_enable' ? '已开启：每 2 小时采集 1 篇 Tech 文章。' : '自动采集已暂停。');
          sendResponse(result);
        } else if (message.action === 'auto_run') {
          if (running || automationBusy) throw new Error('采集任务正在运行');
          await automationTick(true, message.column || 'tech');
          sendResponse({ ok: true });
        } else { throw new Error('未知自动采集操作'); }
      } catch (error) { sendResponse({ error: error.message }); }
    })();
  } else if (message.action === 'stop') {
    stopRequested = true;
    setStatus('已请求停止，当前页面处理后结束。').then(() => sendResponse({ ok: true }));
  } else if (['batch', 'tech', 'column_batch'].includes(message.action)) {
    (async () => {
      try {
        const { autoTask } = await chrome.storage.local.get('autoTask');
        if (running || automationBusy || autoTask) throw new Error('采集任务正在运行，请先暂停自动采集');
        runBatch(message.action === 'column_batch' ? message.column : message.action === 'tech' ? 'tech' : null);
        sendResponse({ ok: true });
      } catch (error) { sendResponse({ error: error.message }); }
    })();
  } else if (message.action === 'capture') {
    (async () => {
      let ownsCapture = false;
      try {
        const { autoTask } = await chrome.storage.local.get('autoTask');
        if (running || automationBusy || autoTask) throw new Error('请先停止批量或自动任务');
        running = true;
        ownsCapture = true;
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.url?.startsWith('https://www.bloomberg.com/')) throw new Error('请先打开 Bloomberg.com 主站文章');
        const result = await captureTab(tab.id);
        await setStatus(result.saved ? `已保存：${result.title}\n${result.paragraph_count} 段，${result.word_count} 词，${result.takeaways_count ?? 0} 条要点。\n正文完整性待核验。` : `尚未取得正文：${result.status}`);
        sendResponse({ ok: true, saved: !!result.saved });
      } catch (error) { sendResponse({ error: error.message }); }
      finally { if (ownsCapture) running = false; }
    })();
  } else { sendResponse({ error: '未知操作' }); }
  return true;
});

// Durable per-page steps: a worker restart is recovered by the next alarm.
let automationBusy = false;
async function automationOwner() {
  let { autoOwner } = await chrome.storage.local.get('autoOwner');
  if (!autoOwner) {
    autoOwner = crypto.randomUUID();
    await chrome.storage.local.set({ autoOwner });
  }
  return autoOwner;
}
async function automationFetch(action, payload) {
  const response = await fetch(`${BRIDGE}/automation/bloomberg/${action}`, {
    method: payload ? 'POST' : 'GET',
    headers: payload ? { 'Content-Type': 'application/json' } : {},
    body: payload ? JSON.stringify(payload) : undefined,
    signal: AbortSignal.timeout(8000)
  });
  const output = await response.json();
  if (!response.ok) {
    const error = new Error(output.detail || '自动采集服务不可用');
    error.status = response.status;
    throw error;
  }
  return output;
}
async function clearAutomation(keepTab) {
  const { autoTask } = await chrome.storage.local.get('autoTask');
  await chrome.storage.local.set({ autoTask: null });
  if (autoTask?.tabId && !keepTab) {
    try { await chrome.tabs.remove(autoTask.tabId); } catch (_) {}
  }
}
async function openAutomationStep(step) {
  await clearAutomation(false);
  // Persist intent before opening a page so recovery never loses the claimed task.
  const task = { ...step, deadline: Date.now() + 45000, tabId: null };
  await chrome.storage.local.set({ autoTask: task });
  const tab = await chrome.tabs.create({ url: step.url, active: false });
  task.tabId = tab.id;
  await chrome.storage.local.set({ autoTask: task });
  await setStatus(step.action === 'discover' ? `自动采集：正在读取 ${step.column || 'tech'} 栏目...` : '自动采集：正在读取本轮唯一一篇文章...');
}
async function submitAutomation(task, owner) {
  let output;
  try {
    output = await automationFetch(task.action === 'discover' && task.payload.discovery ? 'discovery' : 'result',
      { owner, run_id: task.run_id, ...task.payload });
  } catch (error) {
    if (![400, 422].includes(error.status) || !task.payload.discovery) throw error;
    const discovery = task.payload.discovery;
    // Retry DOM discovery within this run; no article has been attempted yet.
    if (error.status === 422 && (task.discoveryRetries || 0) < 2) {
      task.discoveryRetries = (task.discoveryRetries || 0) + 1;
      delete task.payload;
      await chrome.storage.local.set({ autoTask: task });
      await setStatus(`栏目尚未加载出文章，等待重试 (${task.discoveryRetries}/2)：${error.message}`);
      return;
    }
    task.payload = { error: 'network_error', error_detail:
      `discovery HTTP ${error.status}: ${error.message}; page=${discovery.url}; title=${discovery.page_title}; links=${discovery.links?.length || 0}`.slice(0, 1500) };
    await chrome.storage.local.set({ autoTask: task });
    output = await automationFetch('result', { owner, run_id: task.run_id, ...task.payload });
  }
  if (output.action === 'article') {
    await openAutomationStep(output);
  } else {
    const pause = ['blocked', 'subscription_gate', 'tab_closed'].includes(output.status);
    await clearAutomation(pause);
    await setStatus(pause ? `自动采集已暂停：${output.status}。处理后点击“开启 / 恢复”。` :
      `本轮自动采集结束：${output.saved ? '保存 1 篇正文候选' : '保存 0 篇'}（${output.status}）。${output.detail || ''} 下轮时间见自动计划。`);
  }
}
async function automationTick(immediate = false, column = null) {
  if (automationBusy || running) return;
  automationBusy = true;
  try {
    const owner = await automationOwner();
    let { autoTask: task } = await chrome.storage.local.get('autoTask');
    // Replay an unacknowledged result before asking for new work.
    if (task?.payload) { await submitAutomation(task, owner); return; }
    const step = await automationFetch('tick', { owner, immediate, ...(immediate && column ? { column } : {}) });
    if (['idle', 'busy'].includes(step.action)) {
      if (task) await clearAutomation(!!step.pause_reason);
      return;
    }
    if (!task || task.run_id !== step.run_id || task.action !== step.action || task.url !== step.url) {
      await openAutomationStep(step);
      return;
    }
    if (!task.tabId) { await openAutomationStep(step); return; }
    let tab;
    try { tab = await chrome.tabs.get(task.tabId); }
    catch (_) { task.payload = { error: 'tab_closed' }; }
    if (!task.payload && tab.status !== 'complete' && Date.now() > task.deadline) task.payload = { error: 'timeout' };
    if (!task.payload && tab.status !== 'complete') return;
    if (!task.payload) {
      // Give hydration time; the alarm is the fallback if this worker is stopped.
      await delay(3000);
      try {
        let [{ result }] = await chrome.scripting.executeScript({ target: { tabId: task.tabId },
          func: task.action === 'discover' ? extractTechLinks : extractArticle,
          args: task.action === 'discover' ? [{ id: task.column || 'tech' }] : [] });
        if (task.action === 'discover') {
          // A complete tab can still be hydrating. Poll the DOM before reporting an empty column.
          for (let attempt = 0; attempt < 5 && !result.blocked && !result.gated && !result.links?.length; attempt++) {
            await delay(2000);
            [{ result }] = await chrome.scripting.executeScript({ target: { tabId: task.tabId },
              func: extractTechLinks, args: [{ id: task.column || 'tech' }] });
          }
          task.payload = { discovery: result };
        } else {
          const normalized = value => new URL(value).origin + new URL(value).pathname.replace(/\/$/, '');
          if (normalized(result.url) !== normalized(task.url) || (result.canonical_url && normalized(result.canonical_url) !== normalized(task.url))) {
            task.payload = { error: 'network_error', error_detail: `Article URL mismatch: expected=${task.url}; actual=${result.url}; canonical=${result.canonical_url}`.slice(0, 1500) };
          } else {
            task.payload = { capture: { ...result, column: task.column || 'tech' } };
          }
        }
      } catch (error) { task.payload = { error: 'network_error', error_detail: `Browser extraction (${task.action}): ${error.message}`.slice(0, 1500) }; }
    }
    await chrome.storage.local.set({ autoTask: task });
    await submitAutomation(task, owner);
  } catch (error) {
    if (error.status === 409) await clearAutomation(false);
    await setStatus(`自动采集等待恢复：${error.message}。未确认结果将在服务恢复后重试提交。`);
  } finally { automationBusy = false; }
}
async function ensureAutomationAlarm() {
  if (!await chrome.alarms.get('tech-automation')) {
    await chrome.alarms.create('tech-automation', { periodInMinutes: 1 });
  }
}
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'tech-automation') automationTick();
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === 'complete') {
    chrome.storage.local.get('autoTask').then(({ autoTask }) => {
      if (autoTask?.tabId === tabId) automationTick();
    });
  }
});
chrome.tabs.onRemoved.addListener(tabId => {
  chrome.storage.local.get('autoTask').then(async ({ autoTask }) => {
    if (autoTask?.tabId === tabId && !autoTask.payload) {
      await chrome.storage.local.set({ autoTask: { ...autoTask, payload: { error: 'tab_closed' } } });
      automationTick();
    }
  });
});
chrome.runtime.onInstalled.addListener(() => {
  ensureAutomationAlarm();
  installCaptureMenus();
  setStatus('采集器已更新：支持右键入库，以及每 2 小时采集 1 篇 Tech 文章。');
});
chrome.runtime.onStartup.addListener(() => { ensureAutomationAlarm(); automationTick(); });
ensureAutomationAlarm();

const ARTICLE_PATTERNS = [
  'https://www.bloomberg.com/news/articles/*',
  'https://www.bloomberg.com/opinion/articles/*',
  'https://www.bloomberg.com/news/newsletters/*',
  'https://www.bloomberg.com/opinion/newsletters/*',
  'https://www.bloomberg.com/news/features/*',
  'https://www.bloomberg.com/features/*'
];
function articleUrl(value) {
  const url = new URL(value);
  if (url.origin !== 'https://www.bloomberg.com' ||
      !/^\/(news|opinion)\/(articles|newsletters)\/|^\/(news\/)?features\//.test(url.pathname)) {
    throw new Error('请选择 Bloomberg 主站文章');
  }
  return url.origin + url.pathname.replace(/\/$/, '');
}
function installCaptureMenus() {
  // Callback form also supports Chrome 120–122.
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: 'bloomberg-save-page', title: '将当前 Bloomberg 文章入库',
      contexts: ['page', 'selection'], documentUrlPatterns: ARTICLE_PATTERNS });
    chrome.contextMenus.create({ id: 'bloomberg-save-link', title: '将这篇 Bloomberg 文章入库',
      contexts: ['link'], targetUrlPatterns: ARTICLE_PATTERNS });
  });
}
async function contextNotice(tabId, message) {
  if (!tabId) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId }, args: [message], func: text => {
      document.getElementById('content-factory-capture-notice')?.remove();
      const notice = document.createElement('div');
      notice.id = 'content-factory-capture-notice';
      notice.textContent = text;
      notice.style.cssText = 'position:fixed;right:20px;bottom:20px;z-index:2147483647;max-width:420px;padding:14px 18px;background:#202124;color:white;border-radius:10px;font:14px/1.5 system-ui;box-shadow:0 3px 16px #0005;pointer-events:none;white-space:pre-wrap';
      document.documentElement.appendChild(notice);
      setTimeout(() => notice.remove(), 8000);
    } });
  } catch (_) { /* The popup remains available when the source page forbids injection. */ }
}
async function captureFromContext(info, sourceTab) {
  let createdTab = null;
  let ownsRun = false;
  try {
    const { autoTask } = await chrome.storage.local.get('autoTask');
    if (running || automationBusy || autoTask) {
      throw new Error('已有采集任务运行，请等待结束或先暂停自动采集。');
    }
    running = true;
    ownsRun = true;
    stopRequested = false;
    const expected = articleUrl(info.menuItemId === 'bloomberg-save-link' ? info.linkUrl : sourceTab?.url);
    await setStatus('右键入库：正在读取文章...');
    await contextNotice(sourceTab?.id, '正在将 Bloomberg 文章入库...');
    let tabId = sourceTab?.id;
    if (info.menuItemId === 'bloomberg-save-link') {
      createdTab = await chrome.tabs.create({ url: expected, active: false });
      tabId = createdTab.id;
      await waitForLoad(tabId);
      if (stopRequested) throw new Error('右键采集已停止');
      const loaded = await chrome.tabs.get(tabId);
      if (articleUrl(loaded.url) !== expected) throw new Error('文章跳转到了其他页面，请打开文章后再入库');
    }
    const result = await captureTab(tabId);
    const message = result.saved ? `已入库：${result.title}\n${result.paragraph_count} 段，${result.word_count} 词，${result.takeaways_count ?? 0} 条要点；全文完整性待核验。` :
      `未入库：${result.status}。请检查登录或文章正文。`;
    if (createdTab && result.saved) {
      await chrome.tabs.remove(createdTab.id);
      createdTab = null;
    }
    await setStatus(message);
    await contextNotice(sourceTab?.id, message);
    // Keep unsuccessful linked pages for login/verification or body inspection.
    if (createdTab) await chrome.tabs.update(createdTab.id, { active: true });
  } catch (error) {
    const message = `右键入库失败：${error.message}`;
    await setStatus(message);
    await contextNotice(sourceTab?.id, message);
  } finally {
    if (ownsRun) running = false;
  }
}
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (['bloomberg-save-page', 'bloomberg-save-link'].includes(info.menuItemId)) {
    captureFromContext(info, tab);
  }
});
