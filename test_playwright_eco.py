from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    try:
        browser = p.chromium.launch(
            channel='chrome',
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox'
            ]
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto('https://www.economist.com/britain/2026/09/23/ai-written-speeches-are-taking-over-politics', timeout=30000)
        page.wait_for_timeout(6000)
        
        title = page.locator('h1').first.inner_text()
        print('H1 Title:', title)
        
        paras = page.locator('article p, [data-component="paragraph"] p, main p').all_inner_texts()
        print('Paragraphs count:', len(paras))
        for idx, para in enumerate(paras[:4]):
            print(f'P{idx+1}: {para[:80]}...')
            
        cookies = context.cookies()
        print('Cookies collected count:', len(cookies))
        
        browser.close()
    except Exception as e:
        print('Error:', e)
