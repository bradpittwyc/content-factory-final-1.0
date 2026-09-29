# -*- coding: utf-8 -*-
"""
Interactive FT login helper:
Opens visible browser, autofills credentials, waits for user to pass CAPTCHA/login,
and automatically extracts and saves the real FTSession cookies.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

SESSION_FILE = Path(__file__).parent / "ft_session.json"
COOKIE_FILE = Path(__file__).parent / "data" / "ft_cookie.txt"

EMAIL = "PerrinCove9163@hotmail.com"
PWD = "Abba12345@"

async def run_gui_login():
    print("Opening visible browser for FT login...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
        page = await context.new_page()

        print("Navigating to https://accounts.ft.com/login ...")
        await page.goto("https://accounts.ft.com/login", wait_until="domcontentloaded")
        
        # Try autofilling email
        try:
            await page.wait_for_selector("input[type='email'], input#enter-email", timeout=6000)
            await page.fill("input[type='email'], input#enter-email", EMAIL)
            await page.press("input[type='email'], input#enter-email", "Enter")
            print("Autofilled email!")
        except Exception as e:
            print("Autofill email skip:", e)

        print("\n>>> Waiting for user to complete login in the opened browser window...")
        print(">>> Once logged in, the script will automatically detect and save the session!")

        # Wait loop until user is logged in
        for _ in range(120): # wait up to 120 seconds
            await asyncio.sleep(2)
            cookies = await context.cookies()
            auth_cookies = [c for c in cookies if c.get("name") in ["FTSession", "FTSession_s", "FT_User", "FTClientSessionId"]]
            names = [c["name"] for c in auth_cookies]
            
            # Check if logged in (url changed to ft.com and not accounts login, or FTSession exists)
            cur_url = page.url
            if ("FTSession" in names or "FTSession_s" in names) and ("accounts.ft.com/login" not in cur_url or "myft" in cur_url):
                print(f"\n🎉 Login detected! Cookies: {names}")
                
                # Save Playwright storage state
                state = await context.storage_state()
                SESSION_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
                
                # Save raw cookie header
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                COOKIE_FILE.parent.mkdir(exist_ok=True)
                COOKIE_FILE.write_text(cookie_str, encoding="utf-8")
                
                print(f"Session saved successfully to {SESSION_FILE} and {COOKIE_FILE}!")
                await browser.close()
                return True

        print("Login timed out.")
        await browser.close()
        return False

if __name__ == "__main__":
    asyncio.run(run_gui_login())
