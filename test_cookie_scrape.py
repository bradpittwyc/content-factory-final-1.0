# -*- coding: utf-8 -*-
"""
Test scraping articles with injected session cookies
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SESSION_FILE = Path("ft_session.json")
OUTPUT_DIR = Path("ft_articles")
OUTPUT_DIR.mkdir(exist_ok=True)

TEST_URLS = [
    "https://www.ft.com/content/d751ad99-531d-4990-9a4c-ee89a9fc1b2d",
    "https://www.ft.com/content/00f94018-e658-4545-b16e-1bc00e19b754",
    "https://www.ft.com/content/33344fa5-6a25-4d72-8934-528526dd89bd",
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

async def test_scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            storage_state=str(SESSION_FILE),
            viewport={"width": 1280, "height": 900},
            user_agent=UA
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        page = await context.new_page()

        for idx, url in enumerate(TEST_URLS, 1):
            print(f"\n[{idx}/{len(TEST_URLS)}] Visiting: {url}")
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                data = await page.evaluate("""() => {
                    const title = document.querySelector('h1')?.innerText?.trim() || '';
                    const standfirst = document.querySelector('.article__standfirst, .standfirst, [data-component="standfirst"]')?.innerText?.trim() || '';
                    
                    // Body text paragraphs
                    const pEls = Array.from(document.querySelectorAll('article p, .article__content p, [data-component="article-body"] p, .n-content-body p'));
                    const paragraphs = pEls.map(p => p.innerText.trim()).filter(t => t.length > 20);
                    
                    const isPaywalled = document.body.innerText.includes('Subscribe to read') || 
                                        document.body.innerText.includes('Subscribe now') ||
                                        !!document.querySelector('[class*="barrier"], [class*="paywall"]');

                    return {
                        title,
                        standfirst,
                        paragraphsCount: paragraphs.length,
                        paragraphs: paragraphs,
                        isPaywalled
                    };
                }""")

                print(f"  Title: {data['title']}")
                print(f"  Standfirst: {data['standfirst']}")
                print(f"  Paragraphs count: {data['paragraphsCount']}")
                print(f"  Paywalled?: {data['isPaywalled']}")
                if data['paragraphs']:
                    print("  --- Preview of first 2 paragraphs ---")
                    for p in data['paragraphs'][:2]:
                        print(f"    {p}\n")

                # Save article output
                out_path = OUTPUT_DIR / f"article_{idx}.json"
                out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

            except Exception as e:
                print(f"  Error: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_scrape())
