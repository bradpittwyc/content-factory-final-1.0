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
  let paragraphs = [], bodyBlocks = [], bodySelector = '';
  const diagnostics = [];
  bodySearch: for (const selector of selectors) {
    const nodes = [...document.querySelectorAll(selector)];
    for (const node of nodes) {
      const blocks = [...node.querySelectorAll('p, li, h2, h3, blockquote')]
        .filter(element => visible(element) && !element.querySelector('p, li, h2, h3, blockquote'))
        .filter(element => !element.closest('figure, aside, nav'))
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
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const value = JSON.parse(script.textContent);
      const nodes = Array.isArray(value) ? value : [value];
      for (const node of nodes.flatMap(item => item['@graph'] || [item])) {
        if (/Article/.test(String(node['@type']))) metadata = node;
      }
    } catch (_) {}
  }
  let authors = metadata.author || [];
  if (!Array.isArray(authors)) authors = [authors];
  authors = authors.map(author => typeof author === 'string' ? author : author.name).filter(Boolean);
  return {
    url: location.href, page_title: pageTitle,
    title: document.querySelector('h1')?.innerText.trim() || '',
    paragraphs, published_at: metadata.datePublished || document.querySelector('meta[property="article:published_time"]')?.content || null,
    authors, blocked, gated: gate, body_selector: bodySelector, diagnostics,
    body_blocks: bodyBlocks, capture_version: 2
  };
}

function extractTechLinks() {
  const blocked = /are you a robot|access denied|just a moment|security verification/i.test(document.title);
  const root = document.querySelector('main, [role="main"], #main-content') || document.body;
  const links = new Map();
  for (const anchor of root.querySelectorAll('a[href]')) {
    if (anchor.closest('header, footer, nav, aside, [role="navigation"]')) continue;
    const url = new URL(anchor.href, location.href);
    if (url.hostname !== 'www.bloomberg.com' || url.protocol !== 'https:') continue;
    if (!/^\/(news|opinion)\/(articles|newsletters)\/|^\/(news\/)?features\//.test(url.pathname)) continue;
    const normalized = url.origin + url.pathname.replace(/\/$/, '');
    const title = anchor.innerText.trim() || anchor.getAttribute('aria-label') || '';
    if (!links.has(normalized) || (!links.get(normalized).title && title)) links.set(normalized, { url: normalized, title });
  }
  return { url: location.href, page_title: document.title, blocked, links: [...links.values()] };
}

async function captureTab(tabId, column = null) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func: extractArticle });
  if (column) result.column = column;
  const response = await fetch(`${BRIDGE}/capture`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
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
    if (column === 'tech') {
      await setStatus('正在读取 Bloomberg Tech 栏目文章链接...');
      tab = await chrome.tabs.create({ url: 'https://www.bloomberg.com/technology', active: true });
      await waitForLoad(tab.id);
      if (stopRequested) { await setStatus('Tech 采集已停止'); return; }
      const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extractTechLinks });
      const discoveryResponse = await fetch(`${BRIDGE}/columns/tech/discover`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(result) });
      const discovery = await discoveryResponse.json();
      if (!discoveryResponse.ok) throw new Error(discovery.detail || 'Tech 栏目链接读取失败');
      await setStatus(`Tech 栏目发现 ${discovery.candidate_count} 个文章链接，开始试抓...`);
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
    sendResponse({ api_version: 3, capture_version: 2, extension_version: chrome.runtime.getManifest().version });
    return;
  } else if (message.action === 'stop') {
    stopRequested = true;
    setStatus('已请求停止，当前页面处理后结束。').then(() => sendResponse({ ok: true }));
  } else if (message.action === 'batch' || message.action === 'tech') {
    if (running) { sendResponse({ error: '批量任务正在运行' }); return; }
    runBatch(message.action === 'tech' ? 'tech' : null);
    sendResponse({ ok: true });
  } else if (message.action === 'capture') {
    (async () => {
      try {
        if (running) throw new Error('请先停止批量任务');
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab?.url?.startsWith('https://www.bloomberg.com/')) throw new Error('请先打开 Bloomberg.com 主站文章');
        const result = await captureTab(tab.id);
        await setStatus(result.saved ? `已保存：${result.title}\n${result.paragraph_count} 段，${result.word_count} 词。\n正文完整性待核验。` : `尚未取得正文：${result.status}`);
        sendResponse({ ok: true });
      } catch (error) { sendResponse({ error: error.message }); }
    })();
  } else { sendResponse({ error: '未知操作' }); }
  return true;
});

chrome.runtime.onInstalled.addListener(() => setStatus('采集器已更新。请点击“试抓 Tech 前 10 篇”开始栏目验证。'));
