"""
Financial Times Scraper
=======================
两步走：
  Step 1:  python ft_scraper.py login
           打开可视化浏览器 → 你手动登录 FT → 按 Enter → 保存 session 到 ft_session.json

  Step 2:  python ft_scraper.py scrape [URL]
           用保存的 session 抓取文章正文，无需再次登录

  Step 3:  python ft_scraper.py feed [section]
           抓取 FT RSS 某版块的最新文章列表 + 自动获取全文
           section 可选: home, technology, markets, companies, world (默认 home)

  Step 4:  python ft_scraper.py monitor [section] [interval_minutes]
           持续监控，定期拉取新文章 (默认 60 分钟)
"""

import asyncio
import json
import sys
import time
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

SESSION_FILE = Path(__file__).parent / "ft_session.json"
OUTPUT_DIR   = Path(__file__).parent / "ft_articles"
OUTPUT_DIR.mkdir(exist_ok=True)

FT_RSS_FEEDS = {
    "home":        "https://www.ft.com/rss/home",
    "technology":  "https://www.ft.com/technology?format=rss",
    "markets":     "https://www.ft.com/markets?format=rss",
    "companies":   "https://www.ft.com/companies?format=rss",
    "world":       "https://www.ft.com/world?format=rss",
    "opinion":     "https://www.ft.com/opinion?format=rss",
}

# ------------------------------------------------------------------
# STEP 1: LOGIN — open browser, let user log in, save session
# ------------------------------------------------------------------
async def do_login():
    print("="*60)
    print("  FT 登录模式")
    print("="*60)
    print("即将打开浏览器窗口，请手动完成 FT 登录...")
    print("登录完成后，回到这里按 Enter 保存 session。\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = await browser.new_context(
            viewport=None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        await page.goto("https://www.ft.com/login", wait_until="domcontentloaded")

        print("浏览器已打开，请登录 FT...")
        print("登录完成后，回到终端按 Enter ↵")
        input(">>> 按 Enter 保存 session: ")

        # 验证是否已登录
        current_url = page.url
        cookies = await context.cookies()
        has_session = any(
            c['name'] in ['FT_User', 'FTSession', 'FTSession_s', 'FT_CSRF_Token']
            for c in cookies
        )

        if not has_session:
            print("⚠️  警告：未检测到 FT 登录 cookies，可能未成功登录")
            print("   检测到的 cookies:", [c['name'] for c in cookies[:10]])

        # 保存完整 storage state（cookies + localStorage）
        state = await context.storage_state()
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        cookie_names = [c['name'] for c in state.get('cookies', [])]
        print(f"\n✅ Session 已保存到: {SESSION_FILE}")
        print(f"   共保存 {len(cookie_names)} 个 cookies")
        print(f"   关键 cookies: {[n for n in cookie_names if 'FT' in n or 'session' in n.lower()]}")

        await browser.close()


# ------------------------------------------------------------------
# STEP 2: SCRAPE A SINGLE ARTICLE
# ------------------------------------------------------------------
async def scrape_article(url: str) -> dict:
    if not SESSION_FILE.exists():
        print("❌ 未找到 session 文件，请先运行: python ft_scraper.py login")
        return {}

    print(f"\n正在抓取: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,  # 后台静默运行
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            storage_state=str(SESSION_FILE),
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # 伪装成正常用户，避免触发机器人检测
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)  # 等待动态内容加载

            result = await page.evaluate("""
                () => {
                    // 标题
                    const title = document.querySelector('h1.article-title, h1[data-component="heading"], h1')?.innerText?.trim() || '';

                    // 发布时间
                    const timeEl = document.querySelector('time[datetime], .article-info__time, [data-o-component="o-date"]');
                    const publishedAt = timeEl?.getAttribute('datetime') || timeEl?.innerText?.trim() || '';

                    // 作者
                    const authorEls = document.querySelectorAll('.article__author-name, a[data-trackable="author"], .author');
                    const authors = Array.from(authorEls).map(a => a.innerText.trim()).filter(Boolean);

                    // 正文段落
                    const bodySelectors = [
                        '.article__content-body p',
                        '[data-component="article-body"] p',
                        '.n-content-body p',
                        '.article-body p',
                        'article p'
                    ];
                    let bodyText = '';
                    for (const sel of bodySelectors) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 2) {
                            bodyText = Array.from(els).map(p => p.innerText.trim()).filter(Boolean).join('\\n\\n');
                            break;
                        }
                    }

                    // 摘要 / standfirst
                    const summary = document.querySelector('.article__standfirst, .standfirst, [data-component="standfirst"]')?.innerText?.trim() || '';

                    // 检查是否有付费墙提示
                    const isPaywalled = !!(
                        document.querySelector('.barrier-paywall, .subscription-barrier, #premium-barrier') ||
                        document.body.innerText.includes('Subscribe to read') ||
                        document.body.innerText.includes('SUBSCRIBE NOW')
                    );

                    return { title, publishedAt, authors, summary, bodyText, isPaywalled, url: window.location.href };
                }
            """)

            if result.get('isPaywalled'):
                print("⛔ 检测到付费墙 — session 可能已过期，请重新运行 login")
            elif not result.get('bodyText'):
                print("⚠️  未能提取正文，可能页面结构变化了")
                # 保存原始 HTML 供调试
                html = await page.content()
                debug_file = OUTPUT_DIR / f"debug_{int(time.time())}.html"
                debug_file.write_text(html, encoding="utf-8")
                print(f"   已保存原始 HTML 到: {debug_file}")
            else:
                print(f"✅ 成功！标题: {result['title'][:60]}...")
                print(f"   字数: {len(result.get('bodyText',''))} 字符")
                print(f"   是否付费墙: {result['isPaywalled']}")

            result['scrapedAt'] = datetime.now().isoformat()
            await browser.close()
            return result

        except Exception as e:
            print(f"❌ 抓取失败: {e}")
            await browser.close()
            return {}


# ------------------------------------------------------------------
# STEP 3: FETCH RSS FEED → then scrape each article
# ------------------------------------------------------------------
async def fetch_rss_and_scrape(section: str = "home", max_articles: int = 5):
    feed_url = FT_RSS_FEEDS.get(section, FT_RSS_FEEDS["home"])
    print(f"\n📡 拉取 RSS: {feed_url}")

    articles = []
    try:
        async with httpx.AsyncClient(timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; personal-reader/1.0)"
        }) as client:
            resp = await client.get(feed_url)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = root.findall('.//item')

        print(f"  找到 {len(items)} 篇文章，准备抓取前 {max_articles} 篇...\n")

        for item in items[:max_articles]:
            title_el   = item.find('title')
            link_el    = item.find('link')
            desc_el    = item.find('description')
            pubdate_el = item.find('pubDate')

            url     = link_el.text if link_el is not None else ""
            title   = title_el.text if title_el is not None else ""
            desc    = desc_el.text if desc_el is not None else ""
            pubdate = pubdate_el.text if pubdate_el is not None else ""

            print(f"  [{len(articles)+1}] {title[:70]}")

            # 抓取全文
            article_data = await scrape_article(url)
            article_data.update({
                "rss_title":   title,
                "rss_summary": desc,
                "rss_pubdate": pubdate,
                "section":     section,
            })
            articles.append(article_data)

            # 礼貌延迟
            await asyncio.sleep(3)

    except Exception as e:
        print(f"❌ RSS 拉取失败: {e}")

    # 保存结果
    out_file = OUTPUT_DIR / f"ft_{section}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已保存 {len(articles)} 篇文章到: {out_file}")
    return articles


# ------------------------------------------------------------------
# STEP 4: MONITOR — 定时拉取
# ------------------------------------------------------------------
async def monitor(section: str = "home", interval_minutes: int = 60, max_articles: int = 5):
    print(f"🔄 监控模式: 版块={section}, 间隔={interval_minutes}分钟")
    print("   按 Ctrl+C 停止\n")
    seen_urls = set()

    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 开始新一轮抓取...")
        articles = await fetch_rss_and_scrape(section, max_articles)

        new_articles = [a for a in articles if a.get('url') not in seen_urls]
        seen_urls.update(a.get('url','') for a in articles)

        print(f"  本轮新增 {len(new_articles)} 篇文章")
        print(f"  下次拉取: {interval_minutes} 分钟后")
        await asyncio.sleep(interval_minutes * 60)


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "login":
        await do_login()

    elif cmd == "scrape":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://www.ft.com/"
        result = await scrape_article(url)
        if result:
            print("\n--- 文章内容 ---")
            print(f"标题: {result.get('title','')}")
            print(f"作者: {', '.join(result.get('authors', []))}")
            print(f"时间: {result.get('publishedAt','')}")
            print(f"摘要: {result.get('summary','')[:200]}")
            print(f"\n正文 (前500字):\n{result.get('bodyText','')[:500]}")
            # 保存
            fname = OUTPUT_DIR / f"article_{int(time.time())}.json"
            fname.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n💾 已保存到: {fname}")

    elif cmd == "feed":
        section = sys.argv[2] if len(sys.argv) > 2 else "home"
        count   = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        await fetch_rss_and_scrape(section, count)

    elif cmd == "monitor":
        section  = sys.argv[2] if len(sys.argv) > 2 else "home"
        interval = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        await monitor(section, interval)

    else:
        print(__doc__)

if __name__ == "__main__":
    asyncio.run(main())
