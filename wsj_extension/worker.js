const API = 'http://127.0.0.1:8011/wsj';
let busy = false, stopped = false;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function extractWsjArticle() {
  const visible = el => el && el.getClientRects().length > 0;
  const blocked = /access denied|verify you are human|captcha|robot|just a moment/i.test(document.title) ||
    [...document.querySelectorAll('h1,h2')].some(el => visible(el) && /verify you are human|access denied/i.test(el.innerText));
  const gated = [...document.querySelectorAll('[class*="paywall"], [class*="Paywall"], [data-testid*="paywall"], .wsj-snippet-login, .wsj-snippet-subscribe')]
    .some(el => visible(el) && /subscribe|sign in|log in|subscription/i.test(el.innerText));
  const heading = [...document.querySelectorAll('article h1, main h1, h1')].find(visible);
  const selectors = ['[data-testid="article-body"]', '[data-type="article-body"]',
    'article .article-content', '.article-content', '[class*="ArticleBody"]', '.article-body'];
  let body = null, selector = '';
  for (const value of selectors) {
    body = [...document.querySelectorAll(value)].find(el => visible(el) && el.querySelector('p'));
    if (body) { selector = value; break; }
  }
  const takeaways = [];
  const summary = [...document.querySelectorAll('h2,h3,[role="heading"]')].find(el =>
    visible(el) && /^(key (points|takeaways)|takeaways|what to know)$/i.test(el.innerText.trim()));
  let summaryContainer = null;
  if (summary) {
    let parent = summary.parentElement;
    for (let level = 0; parent && level < 4 && parent !== body; level++, parent = parent.parentElement) {
      const list = [...parent.querySelectorAll('li')].filter(visible);
      if (list.length && list.length <= 15 && (!body || !parent.contains(body))) {
        summaryContainer = parent;
        takeaways.push(...list.map(el => el.innerText.trim()));
        break;
      }
    }
  }
  const body_blocks = body ? [...body.querySelectorAll('p,li,h2,h3,blockquote')].filter(el =>
    visible(el) && !el.closest('aside,nav,figure,[class*="related"],[class*="Related"],[class*="paywall"],[class*="Paywall"]') &&
    !summaryContainer?.contains(el) && !el.parentElement.closest('li,blockquote') &&
    !/^(advertisement|copyright ©|subscribe to continue|sign in to read)/i.test(el.innerText.trim()))
    .map(el => ({ kind: el.tagName.toLowerCase(), text: el.innerText.trim() })).filter(block => block.text) : [];
  const canonical_url = document.querySelector('link[rel="canonical"]')?.href || location.href;
  let metadata = {};
  const inspect = value => {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) { value.forEach(inspect); return; }
    const types = [].concat(value['@type'] || []);
    if (types.some(type => /^(NewsArticle|Article|ReportageNewsArticle)$/.test(type))) {
      const pageUrl = value.url || (typeof value.mainEntityOfPage === 'string' ? value.mainEntityOfPage : value.mainEntityOfPage?.['@id']);
      if (!pageUrl || new URL(pageUrl, location.href).pathname === new URL(canonical_url).pathname) metadata = value;
    }
    if (value['@graph']) inspect(value['@graph']);
  };
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try { inspect(JSON.parse(script.textContent)); } catch (_) {}
  }
  const authors = [].concat(metadata.author || []).map(author => typeof author === 'string' ? author : author.name).filter(Boolean);
  return { url: location.href, canonical_url, title: heading?.innerText.trim() || '',
    standfirst: document.querySelector('[data-testid="article-subheading"], .sub-head, [class*="SubHeadline"]')?.innerText.trim() || '',
    authors, published_at: metadata.datePublished || document.querySelector('meta[property="article:published_time"]')?.content || null,
    body_selector: selector, body_blocks, takeaways, blocked, gated };
}

function extractWsjLinks() {
  const root = document.querySelector('main,[role="main"]') || document.body;
  const links = new Map();
  for (const anchor of root.querySelectorAll('a[href]')) {
    if (anchor.closest('nav,header,footer,aside')) continue;
    const url = new URL(anchor.href, location.href);
    if (url.origin !== 'https://www.wsj.com' || !/-(?:[0-9a-f]{8}|\d{10,})$/i.test(url.pathname.replace(/\/$/, ''))) continue;
    const clean = url.origin + url.pathname.replace(/\/$/, '');
    links.set(clean, { url: clean, title: anchor.innerText.trim() });
  }
  return { url: location.origin + location.pathname.replace(/\/$/, ''), links: [...links.values()],
    blocked: /access denied|captcha|robot|just a moment/i.test(document.title) };
}

async function api(path, payload) {
  const response = await fetch(API + path, { method: payload ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json' }, body: payload ? JSON.stringify(payload) : undefined,
    signal: AbortSignal.timeout(8000) });
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : `WSJ service HTTP ${response.status}`);
  return result;
}
async function waitForPage(id) {
  for (let count = 0; count < 45; count++) {
    if (stopped) throw Error('已停止');
    if ((await chrome.tabs.get(id)).status === 'complete') { await delay(3000); return; }
    await delay(1000);
  }
  throw Error('页面加载超时');
}
async function captureTab(id, section = null, expected = null) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: id }, func: extractWsjArticle });
  if (expected && new URL(result.url).pathname !== new URL(expected).pathname) throw Error('文章跳转到了其他页面，请检查登录状态');
  return api('/capture', { ...result, section });
}
async function batch(section) {
  let tab = await chrome.tabs.create({ url: `https://www.wsj.com/${section}`, active: false });
  let saved = 0, attempted = 0;
  try {
    await waitForPage(tab.id);
    const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extractWsjLinks });
    await api(`/columns/${section}/discover`, result);
    const queue = await api(`/queue/${section}`);
    await chrome.tabs.remove(tab.id); tab = null;
    for (const article of queue.articles.slice(0, 10)) {
      if (stopped) break;
      tab = await chrome.tabs.create({ url: article.url, active: false });
      await waitForPage(tab.id);
      attempted++;
      const result = await captureTab(tab.id, section, article.url);
      if (['blocked', 'subscription_gate'].includes(result.status)) {
        await chrome.tabs.update(tab.id, { active: true });
        throw Error(`需要处理验证或订阅登录；已保存 ${saved} 篇`);
      }
      if (result.saved) saved++;
      await chrome.tabs.remove(tab.id); tab = null;
      await delay(1500);
    }
    return { message: `试抓结束：尝试 ${attempted} 篇，保存 ${saved} 篇正文候选，请核验完整性。` };
  } catch (error) {
    if (tab) try { await chrome.tabs.update(tab.id, { active: true }); } catch (_) {}
    throw error;
  }
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.action === 'stop') { stopped = true; respond({ message: '停止请求已接收' }); return; }
  if (!['capture', 'batch'].includes(message.action)) return;
  if (busy) { respond({ error: 'WSJ 采集正在执行' }); return; }
  busy = true; stopped = false;
  (async () => {
    try {
      if (message.action === 'batch') respond(await batch(message.section));
      else {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        respond(await captureTab(tab.id));
      }
    } catch (error) { respond({ error: error.message }); }
    finally { busy = false; }
  })();
  return true;
});
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: 'wsj-page', title: '将当前 WSJ 文章入库', contexts: ['page', 'selection'], documentUrlPatterns: ['https://www.wsj.com/*'] });
    chrome.contextMenus.create({ id: 'wsj-link', title: '将这篇 WSJ 文章入库', contexts: ['link'], targetUrlPatterns: ['https://www.wsj.com/*'] });
  });
});
chrome.contextMenus.onClicked.addListener(async (info, original) => {
  if (busy) return;
  busy = true; stopped = false;
  let tab = original, created = false;
  try {
    if (info.menuItemId === 'wsj-link') {
      tab = await chrome.tabs.create({ url: info.linkUrl, active: false }); created = true;
      await waitForPage(tab.id);
    }
    const result = await captureTab(tab.id, null, created ? info.linkUrl : null);
    if (created && result.saved) await chrome.tabs.remove(tab.id);
    else if (created) await chrome.tabs.update(tab.id, { active: true });
    await chrome.scripting.executeScript({ target: { tabId: original.id }, func: message => {
      const notice = document.createElement('div'); notice.textContent = message;
      notice.style.cssText = 'position:fixed;right:20px;top:20px;z-index:2147483647;background:#16202c;color:white;padding:18px;border-radius:10px';
      document.body.append(notice); setTimeout(() => notice.remove(), 8000);
    }, args: [result.saved ? `WSJ 已入库：${result.title}` : `WSJ 未入库：${result.status}`] });
  } catch (error) {
    if (created) try { await chrome.tabs.update(tab.id, { active: true }); } catch (_) {}
    await chrome.action.setBadgeText({ text: '!' });
    await chrome.action.setTitle({ title: `WSJ 采集失败：${error.message}` });
  } finally { busy = false; }
});
