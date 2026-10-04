# -*- coding: utf-8 -*-
"""
Bloomberg syndication and open-channel scraper store.
Fetches real-time Bloomberg wire articles from BNN Bloomberg (Bloomberg LP Joint Venture).
Requires ZERO logins, ZERO cookies, and has ZERO paywalls.
"""
import os
import re
import json
import time
from datetime import datetime, timedelta, timezone


import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
BLOOMBERG_ARTICLES_FILE = DATA_DIR / "bloomberg_articles.json"

SECTIONS = [
    ("Technology & AI", "https://www.bnnbloomberg.ca/business/artificial-intelligence/"),
    ("Business & Markets", "https://www.bnnbloomberg.ca/business/"),
    ("Investing", "https://www.bnnbloomberg.ca/investing/")
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}

def parse_article_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s_str = str(s).strip()
    m = re.search(r'(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})', s_str)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    m2 = re.search(r'(\d{4}-\d{2}-\d{2})', s_str)
    if m2:
        try:
            return datetime.strptime(m2.group(1), "%Y-%m-%d")
        except Exception:
            pass
    return None

def load_bloomberg_articles() -> List[Dict[str, Any]]:
    if not BLOOMBERG_ARTICLES_FILE.exists():
        return []
    try:
        data = json.loads(BLOOMBERG_ARTICLES_FILE.read_text(encoding="utf-8"))
        articles = data if isinstance(data, list) else []
        cutoff = datetime.now() - timedelta(days=3)
        kept = []
        changed = False
        for a in articles:
            dt = parse_article_datetime(a.get("scraped_at")) or parse_article_datetime(a.get("published_at"))
            if dt and dt < cutoff:
                changed = True
            else:
                kept.append(a)
        if changed:
            save_bloomberg_articles(kept)
        return kept
    except Exception as e:
        print(f"Error loading bloomberg articles: {e}")
        return []

def save_bloomberg_articles(articles: List[Dict[str, Any]]) -> None:
    BLOOMBERG_ARTICLES_FILE.write_text(json.dumps(articles, indent=2, ensure_ascii=False), encoding="utf-8")


def upsert_bloomberg_article(art: Dict[str, Any]) -> None:
    articles = load_bloomberg_articles()
    idx = next((i for i, a in enumerate(articles) if a.get("url") == art.get("url") or a.get("title") == art.get("title")), None)
    if idx is not None:
        articles[idx] = art
    else:
        articles.insert(0, art)
    save_bloomberg_articles(articles)

def scrape_single_bloomberg_url(url: str, section: str = "Business") -> Optional[Dict[str, Any]]:
    """Fetch full article content from BNN Bloomberg syndication."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            
            # Title
            h1 = soup.find("h1")
            title = h1.get_text().strip() if h1 else ""
            if not title:
                return None
            
            # Subtitle / Standfirst
            standfirst_el = soup.find("div", class_=re.compile(r"deck|subheading|summary|standfirst", re.I))
            standfirst = standfirst_el.get_text().strip() if standfirst_el else ""
            
            # Authors / Byline
            byline_el = soup.find("div", class_=re.compile(r"byline|author", re.I))
            authors = []
            if byline_el:
                btxt = byline_el.get_text().strip()
                btxt = re.sub(r"^By\s+", "", btxt)
                btxt = re.sub(r"Opens in new window.*", "", btxt).strip()
                if btxt:
                    authors = [btxt]
            if not authors:
                authors = ["Bloomberg News"]

            # Body Paragraphs
            article_body = soup.find("div", class_=re.compile(r"article-content|article-body|story-content|body-copy", re.I))
            if not article_body:
                article_body = soup
            
            paragraphs = []
            for p in article_body.find_all("p"):
                txt = p.get_text().strip()
                # Exclude ads, copyright, boilerplates, and timestamp lines
                if len(txt) > 30 and not any(k in txt.lower() for k in [
                    "copyright", "all rights reserved", "terms of service", "sign in", "subscribe", 
                    "updated:", "published:", "click here to read", "listen to this article"
                ]):
                    paragraphs.append(txt)
            
            if not paragraphs:
                return None
            
            word_count = sum(len(p.split()) for p in paragraphs)
            if word_count < 150 or len(paragraphs) < 4:
                return None
            
            return {
                "id": "bb_" + str(int(time.time() * 1000)),
                "title": title,
                "url": url,
                "section": section,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "standfirst": standfirst or (paragraphs[0][:150] + "..."),
                "authors": authors,
                "paragraph_count": len(paragraphs),
                "paragraphs": paragraphs,
                "word_count": word_count,
                "is_paywalled": False,
                "scraped_at": datetime.now(timezone.utc).isoformat()

            }
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None

def scan_bloomberg_syndication(limit_per_section: int = 4) -> List[Dict[str, Any]]:
    """Scan all syndication sections and pull new articles into data/bloomberg_articles.json."""
    existing_urls = {a.get("url") for a in load_bloomberg_articles()}
    new_articles = []
    
    for sec_name, sec_url in SECTIONS:
        try:
            req = urllib.request.Request(sec_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                soup = BeautifulSoup(resp.read().decode("utf-8", errors="ignore"), "html.parser")
                candidates = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if re.search(r"/\d{4}/\d{2}/\d{2}/", href):
                        full_url = href if href.startswith("http") else "https://www.bnnbloomberg.ca" + href
                        if full_url not in existing_urls and full_url not in [c[0] for c in candidates]:
                            candidates.append((full_url, sec_name))
                
                print(f"[{sec_name}] Found {len(candidates)} candidate articles")
                for u, s in candidates[:limit_per_section]:
                    art = scrape_single_bloomberg_url(u, s)
                    if art:
                        upsert_bloomberg_article(art)
                        existing_urls.add(u)
                        new_articles.append(art)
                        print(f"  + Added: {art['title'][:40]} ({art['paragraph_count']} paras)")
        except Exception as e:
            print(f"Error in section {sec_name}: {e}")
            
    return new_articles

if __name__ == "__main__":
    print("Testing scan_bloomberg_syndication(limit_per_section=2)...")
    res = scan_bloomberg_syndication(limit_per_section=2)
    print(f"Scan complete. Added {len(res)} articles.")
