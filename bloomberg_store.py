# -*- coding: utf-8 -*-
"""
Public BNN Bloomberg article scraper and local store.
The site carries multiple news providers; preserve the article's actual byline.
"""
import hashlib
import re
import json
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

BLOOMBERG_MAIN_FILE = DATA_DIR / "bloomberg_main_articles.json"

def load_bloomberg_articles() -> List[Dict[str, Any]]:
    articles = []
    if BLOOMBERG_ARTICLES_FILE.exists():
        try:
            data = json.loads(BLOOMBERG_ARTICLES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                articles.extend(data)
        except Exception as e:
            print(f"Error loading bloomberg articles: {e}")

    if BLOOMBERG_MAIN_FILE.exists():
        try:
            main_data = json.loads(BLOOMBERG_MAIN_FILE.read_text(encoding="utf-8"))
            if isinstance(main_data, list):
                existing_urls = {a.get("url") for a in articles}
                for ma in main_data:
                    if ma.get("url") not in existing_urls:
                        articles.append(ma)
        except Exception as e:
            print(f"Error loading bloomberg main articles: {e}")

    cutoff = datetime.now() - timedelta(days=3)
    kept = []
    for a in articles:
        dt = parse_article_datetime(a.get("scraped_at")) or parse_article_datetime(a.get("published_at"))
        if dt and dt < cutoff:
            continue
        kept.append(a)
    return kept

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

def parse_bloomberg_html(html: str, url: str, section: str = "Business") -> Optional[Dict[str, Any]]:
    """Parse only the story body; never treat recommendations as article text."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    body = soup.select_one("article.b-article-body, .article-body, .article-content, .story-content, .body-copy")
    if not title or body is None:
        return None

    metadata = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        nodes = value if isinstance(value, list) else [value]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            candidates = node.get("@graph", [node])
            for candidate in candidates:
                if isinstance(candidate, dict) and "Article" in str(candidate.get("@type", "")):
                    metadata = candidate
                    break

    if str(metadata.get("isAccessibleForFree", "true")).lower() == "false":
        return None
    paragraphs = []
    for paragraph in body.find_all("p"):
        text = paragraph.get_text(" ", strip=True)
        if len(text) > 30 and not any(marker in text.lower() for marker in (
            "copyright", "all rights reserved", "terms of service", "click here to read", "listen to this article"
        )):
            paragraphs.append(text)
    word_count = sum(len(text.split()) for text in paragraphs)
    if len(paragraphs) < 4 or word_count < 150:
        return None

    author_data = metadata.get("author", [])
    if isinstance(author_data, (str, dict)):
        author_data = [author_data]
    elif not isinstance(author_data, list):
        author_data = []
    authors = [a.get("name", "") if isinstance(a, dict) else str(a) for a in author_data]
    authors = [a for a in authors if a]
    if not authors:
        byline = soup.find(["div", "span"], class_=re.compile(r"byline|author", re.I))
        if byline:
            text = re.sub(r"^By\s+", "", byline.get_text(" ", strip=True))
            text = re.sub(r"Opens in new window.*", "", text).strip()
            if text:
                authors = [text]
    published_meta = soup.find("meta", property="article:published_time")
    published_at = metadata.get("datePublished") or (published_meta.get("content") if published_meta else None)
    summary = soup.find("meta", attrs={"name": "description"})
    standfirst = metadata.get("description") or (summary.get("content") if summary else None)
    return {
        "id": "bb_" + hashlib.sha256(url.encode()).hexdigest()[:20],
        "title": title, "url": url, "section": section,
        "published_at": published_at,
        "standfirst": standfirst or (paragraphs[0][:150] + "..."),
        "authors": authors, "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs, "word_count": word_count,
        "is_paywalled": False, "scraped_at": datetime.now(timezone.utc).isoformat()
    }


def scrape_single_bloomberg_url(url: str, section: str = "Business") -> Optional[Dict[str, Any]]:
    """Fetch and parse a public BNN Bloomberg story."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        return parse_bloomberg_html(html, url, section)
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
