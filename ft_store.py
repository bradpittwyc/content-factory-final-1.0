# -*- coding: utf-8 -*-
"""
FT Store & Scraper Engine
Manages FT article caching, RSS discovery, full-text parsing, cookie injection, and export.
"""
import os
import json
import time
import asyncio
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from bs4 import BeautifulSoup
import httpx
from curl_cffi import requests as cffi_requests

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ARTICLES_FILE = DATA_DIR / "ft_articles.json"
COOKIE_FILE = DATA_DIR / "ft_cookie.txt"

# Default RSS feeds for Financial Times
FT_SECTIONS = [
    {"id": "home", "name": "首页头条 (Home)", "url": "https://www.ft.com/rss/home/international"},
    {"id": "technology", "name": "科技与AI (Technology)", "url": "https://www.ft.com/technology?format=rss"},
    {"id": "markets", "name": "全球市场 (Markets)", "url": "https://www.ft.com/markets?format=rss"},
    {"id": "companies", "name": "商业与公司 (Companies)", "url": "https://www.ft.com/companies?format=rss"},
    {"id": "world", "name": "全球新闻 (World)", "url": "https://www.ft.com/world?format=rss"},
    {"id": "opinion", "name": "观点与社论 (Opinion)", "url": "https://www.ft.com/opinion?format=rss"},
    {"id": "lex", "name": "高端专栏 (Lex)", "url": "https://www.ft.com/lex?format=rss"},
]

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def get_saved_cookie() -> str:
    """Read cookie string from data/ft_cookie.txt or fallback to ft_session.json"""
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text(encoding="utf-8").strip()
    session_file = Path(__file__).parent / "ft_session.json"
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            parts = [f"{c['name']}={c['value']}" for c in cookies if 'name' in c and 'value' in c]
            return "; ".join(parts)
        except Exception:
            pass
    return ""

def save_cookie(cookie_str: str) -> None:
    COOKIE_FILE.write_text(cookie_str.strip(), encoding="utf-8")

def load_all_articles() -> List[Dict[str, Any]]:
    if not ARTICLES_FILE.exists():
        return []
    try:
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_all_articles(articles: List[Dict[str, Any]]) -> None:
    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

def upsert_article(article_data: Dict[str, Any]) -> None:
    if article_data.get("security_blocked"):
        return
    if "security verification" in article_data.get("title", "").lower():
        return
    if article_data.get("paragraph_count", 0) < 3:
        return

    articles = load_all_articles()
    # Filter out duplicate by URL
    existing_idx = next((i for i, a in enumerate(articles) if a.get("url") == article_data.get("url")), None)
    if existing_idx is not None:
        articles[existing_idx] = {**articles[existing_idx], **article_data}
    else:
        articles.insert(0, article_data)
    save_all_articles(articles)

def delete_article(url: str) -> bool:
    articles = load_all_articles()
    new_list = [a for a in articles if a.get("url") != url]
    if len(new_list) != len(articles):
        save_all_articles(new_list)
        return True
    return False

def build_headers(cookie_str: Optional[str] = None) -> Dict[str, str]:
    ck = cookie_str if cookie_str is not None else get_saved_cookie()
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "cookie": ck,
        "pragma": "no-cache",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": DEFAULT_UA
    }

def scrape_single_article(url: str, section: str = "General", cookie_str: Optional[str] = None) -> Dict[str, Any]:
    """Scrapes a single article using TLS impersonation and headers."""
    headers = build_headers(cookie_str)
    try:
        res = cffi_requests.get(url, headers=headers, impersonate="chrome124", timeout=25)
        html_text = res.text
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Title
        title_el = soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            og_title = soup.find("meta", property="og:title")
            title = og_title.get("content", "").strip() if og_title else "Financial Times Article"

        # Check security / Cloudflare challenge
        is_security_blocked = (
            "Security Verification" in title or 
            "Just a moment" in title or 
            "Verify you are human" in html_text or 
            "help.ft.com" in html_text or 
            res.status_code == 403
        )
        if is_security_blocked:
            return {
                "id": f"ft_{int(time.time() * 1000)}",
                "url": url,
                "title": "Security Verification Blocked",
                "security_blocked": True,
                "paragraph_count": 0,
                "paragraphs": [],
                "full_text": "",
                "word_count": 0,
                "is_paywalled": True,
                "error": "Cloudflare / FT Security Verification Triggered (CG000 / 403)",
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        # 2. Standfirst / Subtitle
        standfirst_el = soup.select_one(".article__standfirst, .standfirst, [data-component='standfirst']")
        standfirst = standfirst_el.get_text(strip=True) if standfirst_el else ""

        # 3. Authors
        author_els = soup.select(".article__author-name, a[data-trackable='author'], [class*='author-name']")
        authors = list(dict.fromkeys([a.get_text(strip=True) for a in author_els if a.get_text(strip=True)]))

        # 4. Published Time
        time_el = soup.select_one("time[datetime], .article-info__time, [data-o-component='o-date']")
        published_at = time_el.get("datetime") if (time_el and time_el.has_attr("datetime")) else (time_el.get_text(strip=True) if time_el else "")

        # 5. Extract all paragraphs
        p_els = soup.select("article p, .article__content p, [data-component='article-body'] p, .n-content-body p, .article-body p")
        paragraphs = []
        noise_keywords = [
            "Subscribe to read", "Sign up to", "Cookies on the FT", "Terms & Conditions",
            "Save now on essential digital access", "Complete digital access", "Cancel anytime during your trial",
            "Check whether you already have free access", "Digital access for organisations",
            "Save now on our curated print edition", "Discover all the plans currently available",
            "*Hand delivery availability"
        ]

        for p in p_els:
            t = p.get_text(strip=True)
            if len(t) > 20 and not any(k.lower() in t.lower() for k in noise_keywords):
                paragraphs.append(t)

        # Fallback if specific selectors didn't catch
        if not paragraphs:
            for p in soup.find_all("p"):
                t = p.get_text(strip=True)
                if len(t) > 30 and not any(k.lower() in t.lower() for k in noise_keywords):
                    paragraphs.append(t)

        full_text = "\n\n".join(paragraphs)
        word_count = len(full_text.split())

        # Check paywall block
        is_paywalled = (len(paragraphs) == 0) or ("Subscribe to read" in title and len(paragraphs) < 3)

        article_obj = {
            "id": f"ft_{int(time.time() * 1000)}",
            "url": url,
            "title": title,
            "standfirst": standfirst,
            "authors": authors,
            "published_at": published_at,
            "section": section,
            "paragraph_count": len(paragraphs),
            "paragraphs": paragraphs,
            "full_text": full_text,
            "word_count": word_count,
            "is_paywalled": is_paywalled,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        return article_obj

    except Exception as e:
        return {
            "id": f"ft_{int(time.time() * 1000)}",
            "url": url,
            "title": "Failed to scrape",
            "standfirst": "",
            "authors": [],
            "published_at": "",
            "section": section,
            "paragraph_count": 0,
            "paragraphs": [],
            "full_text": "",
            "word_count": 0,
            "is_paywalled": False,
            "error": str(e),
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

async def fetch_section_rss_items(section_id: str, limit: int = 15) -> List[Dict[str, str]]:
    sec = next((s for s in FT_SECTIONS if s["id"] == section_id), FT_SECTIONS[0])
    feed_url = sec["url"]

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": DEFAULT_UA}) as client:
        res = await client.get(feed_url)
        res.raise_for_status()

    root = ET.fromstring(res.text)
    items = root.findall(".//item")
    result = []
    for item in items[:limit]:
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pubdate_el = item.find("pubDate")
        cat_el = item.find("category")

        url = link_el.text if link_el is not None and link_el.text else ""
        title = title_el.text if title_el is not None and title_el.text else ""
        desc = desc_el.text if desc_el is not None and desc_el.text else ""
        pubdate = pubdate_el.text if pubdate_el is not None and pubdate_el.text else ""
        cat = cat_el.text if cat_el is not None and cat_el.text else sec["name"]

        if url and title:
            result.append({
                "url": url,
                "title": title,
                "summary": desc,
                "pubdate": pubdate,
                "section": sec["name"]
            })
    return result
