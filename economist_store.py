# -*- coding: utf-8 -*-
"""
The Economist (经济学人) Store & Scraper Engine
Manages Economist article caching, RSS feeds discovery, full-text parsing,
cookie injection, and browser session synchronization.
"""
import os
import re
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from DrissionPage import ChromiumPage, ChromiumOptions
import threading

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    import requests as cffi_requests

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ARTICLES_FILE = DATA_DIR / "economist_articles.json"
COOKIE_FILE = DATA_DIR / "economist_cookie.txt"

ECONOMIST_SECTIONS = [
    {"id": "leaders", "name": "社论大势 (Leaders)", "url": "https://www.economist.com/leaders/rss.xml"},
    {"id": "briefing", "name": "封面简报 (Briefing)", "url": "https://www.economist.com/briefing/rss.xml"},
    {"id": "finance", "name": "财经与金融 (Finance)", "url": "https://www.economist.com/finance-and-economics/rss.xml"},
    {"id": "business", "name": "全球商业 (Business)", "url": "https://www.economist.com/business/rss.xml"},
    {"id": "science", "name": "前沿科技 (Science & Tech)", "url": "https://www.economist.com/science-and-technology/rss.xml"},
    {"id": "china", "name": "中国观察 (China)", "url": "https://www.economist.com/china/rss.xml"},
    {"id": "the-world-this-week", "name": "本周政经精粹 (The World This Week)", "url": "https://www.economist.com/the-world-this-week/rss.xml"}
]

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def get_saved_cookie() -> str:
    if COOKIE_FILE.exists():
        return COOKIE_FILE.read_text(encoding="utf-8").strip()
    return ""

def save_cookie(cookie_str: str) -> None:
    COOKIE_FILE.write_text(cookie_str.strip(), encoding="utf-8")

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

def load_all_articles() -> List[Dict[str, Any]]:
    if not ARTICLES_FILE.exists():
        return []
    try:
        data = json.loads(ARTICLES_FILE.read_text(encoding="utf-8"))
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
            save_all_articles(kept)
        return kept
    except Exception:
        return []

def save_all_articles(articles: List[Dict[str, Any]]) -> None:
    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)


def upsert_article(article_data: Dict[str, Any]) -> None:
    if article_data.get("security_blocked"):
        return
    if "just a moment" in article_data.get("title", "").lower():
        return
    if article_data.get("paragraph_count", 0) < 3 and not article_data.get("full_text"):
        return

    articles = load_all_articles()
    existing_idx = next((i for i, a in enumerate(articles) if a.get("url") == article_data.get("url")), None)
    if existing_idx is not None:
        articles[existing_idx] = article_data
    else:
        articles.insert(0, article_data)
    save_all_articles(articles)

def delete_article(url: str) -> bool:
    articles = load_all_articles()
    new_articles = [a for a in articles if a.get("url") != url]
    if len(new_articles) < len(articles):
        save_all_articles(new_articles)
        return True
    return False

def build_headers(cookie_str: Optional[str] = None) -> Dict[str, str]:
    ck = cookie_str if cookie_str is not None else get_saved_cookie()
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": DEFAULT_UA,
    }
    if ck:
        headers["cookie"] = ck
    return headers

def parse_economist_html(html_text: str, url: str, section_hint: str = "Leaders") -> Dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")

    # 1. Check Cloudflare Block
    title_el = soup.find("title")
    page_title = title_el.get_text(strip=True) if title_el else ""
    is_blocked = (
        "Just a moment" in page_title or
        "Security Verification" in page_title or
        "challenges.cloudflare.com" in html_text or
        "Verify you are human" in html_text
    )
    if is_blocked:
        return {
            "id": f"eco_{int(time.time() * 1000)}",
            "url": url,
            "title": "Cloudflare Verification Blocked",
            "source": "The Economist",
            "security_blocked": True,
            "paragraph_count": 0,
            "paragraphs": [],
            "full_text": "",
            "word_count": 0,
            "error": "Cloudflare Managed Challenge (403)",
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    # 2. Extract Title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        title = og_title.get("content", "").strip() if og_title else page_title

    # 3. Extract Section
    section = section_hint
    sec_el = soup.select_one("[data-test-id='section-label'], .article__section, [data-component='section-name']")
    if sec_el:
        section = sec_el.get_text(strip=True)

    # 4. Extract Standfirst / Rubric / Subtitle
    standfirst = ""
    rubric_el = soup.select_one("[data-test-id='article-rubric'], .article__subheadline, [data-component='rubric'], .article__description")
    if rubric_el:
        standfirst = rubric_el.get_text(strip=True)
    if not standfirst:
        og_desc = soup.find("meta", property="og:description")
        standfirst = og_desc.get("content", "").strip() if og_desc else ""

    # 5. Extract Authors
    authors = []
    author_els = soup.select(".article__byline, [data-test-id='byline'], .byline")
    for el in author_els:
        txt = el.get_text(strip=True)
        if txt and txt not in authors:
            authors.append(txt)
    if not authors:
        authors = ["The Economist Staff"]

    # 6. Extract Published Date
    pub_date = ""
    time_el = soup.find("time")
    if time_el and time_el.get("datetime"):
        pub_date = time_el["datetime"][:19].replace("T", " ")
    elif time_el:
        pub_date = time_el.get_text(strip=True)
    else:
        meta_date = soup.find("meta", property="article:published_time")
        if meta_date and meta_date.get("content"):
            pub_date = meta_date["content"][:19].replace("T", " ")

    # 7. Extract Body Paragraphs
    paragraphs = []
    
    # Try parsing __NEXT_DATA__ JSON if present
    next_data_el = soup.find("script", id="__NEXT_DATA__")
    if next_data_el and next_data_el.string:
        try:
            next_json = json.loads(next_data_el.string)
            content_nodes = next_json.get("props", {}).get("pageProps", {}).get("content", [])
            for node in content_nodes:
                if isinstance(node, dict):
                    # Economist content node format
                    if node.get("type") == "paragraph" or "paragraph" in str(node.get("type", "")).lower():
                        p_text = node.get("text", "") or ""
                        if not p_text and "children" in node:
                            p_text = "".join([c.get("text", "") for c in node.get("children", []) if isinstance(c, dict)])
                        p_text = p_text.strip()
                        if len(p_text) > 15:
                            paragraphs.append(p_text)
        except Exception:
            pass

    # DOM Paragraph Fallback
    if not paragraphs:
        body_els = soup.select("article p, [data-component='paragraph'] p, .article__body-text, main p")
        noise = [
            "listen to this story", "enjoy more audio", "save time by listening",
            "to stay on top of the biggest stories", "subscriber-only audio",
            "the economist app", "for more coverage of", "subscribers can listen"
        ]
        for p in body_els:
            txt = p.get_text(strip=True)
            if len(txt) > 20 and not any(n in txt.lower() for n in noise):
                paragraphs.append(txt)

    full_text = "\n\n".join(paragraphs)
    word_count = len(re.findall(r'\b\w+\b', full_text))

    return {
        "id": f"eco_{int(time.time() * 1000)}",
        "url": url,
        "title": title or "The Economist Article",
        "source": "The Economist",
        "section": section or "Leaders",
        "standfirst": standfirst,
        "authors": authors,
        "published_at": pub_date or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "paragraphs": paragraphs,
        "paragraph_count": len(paragraphs),
        "word_count": word_count,
        "full_text": full_text,
        "is_paywalled": len(paragraphs) < 3
    }

def scrape_via_reader_fallback(url: str, section: str = "Leaders") -> Optional[Dict[str, Any]]:
    jina_url = f"https://r.jina.ai/{url}"
    try:
        import urllib.request
        req = urllib.request.Request(jina_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=18) as resp:
            content = resp.read().decode("utf-8")
        
        title_m = re.search(r"^Title:\s*(.+)$", content, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else ""
        if title.endswith(" | The Economist"):
            title = title[:-16].strip()
            
        md_start = content.find("Markdown Content:")
        body = content[md_start:] if md_start != -1 else content
        
        paras = []
        noise = ["subscribe", "log in", "create account", "already have an account", "reuse this content", "explore more", "listen to this story"]
        for line in body.splitlines():
            l = line.strip()
            if len(l) > 30 and not l.startswith("#") and not l.startswith("![") and not l.startswith("[") and not l.startswith("*"):
                if not any(n in l.lower() for n in noise):
                    paras.append(l)
                    
        if len(paras) >= 1:
            full_text = "\n\n".join(paras)
            word_count = len(re.findall(r'\b\w+\b', full_text))
            return {
                "id": f"eco_{int(time.time() * 1000)}",
                "url": url,
                "title": title or "The Economist Article",
                "source": "The Economist",
                "section": section,
                "standfirst": "",
                "authors": ["The Economist Staff"],
                "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "paragraphs": paras,
                "paragraph_count": len(paras),
                "word_count": word_count,
                "full_text": full_text,
                "is_paywalled": len(paras) < 3,
                "synced_via_reader": True
            }
    except Exception:
        pass
    return None


_dp_lock = threading.Lock()

def get_dp_page(cookie_str=None):
    co = ChromiumOptions()
    co.set_browser_path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    co.set_local_port(9223)
    co.set_user_data_path(os.path.join(os.path.dirname(__file__), "data", "dp_profile"))
    # Disable headless to bypass Cloudflare reliably
    # co.set_argument("--headless=new")

    page = ChromiumPage(co)
    if cookie_str:
        try:
            page.get("https://www.economist.com/404", timeout=15)
            # parse cookie_str manually to dicts
            cookies_list = []
            for item in cookie_str.split(';'):
                if '=' in item:
                    k, v = item.strip().split('=', 1)
                    cookies_list.append({'name': k, 'value': v, 'domain': '.economist.com'})
            for c in cookies_list:
                page.set.cookies(c)
        except:
            pass
    return page


def scrape_single_article_dp(url: str, section: str = "Leaders", cookie_str: Optional[str] = None) -> Dict[str, Any]:
    with _dp_lock:
        page = None
        try:
            page = get_dp_page(cookie_str)
            page.get(url, timeout=30)
            
            if "just a moment" in page.title.lower() or "verify" in page.title.lower():
                page.wait(10)
                
            page.wait(3) # Wait for React content to render!
            
            h1 = page.ele('tag:h1')
            title = h1.text if h1 else page.title
            
            ps = page.eles('css:article p, [data-component="paragraph"] p, main p')
            paras = []
            noise = ['listen to this story', 'enjoy more audio', 'save time', 'to stay on top', 'subscriber-only', 'the economist app']
            for p in ps:
                txt = p.text.strip()
                if len(txt) > 20 and not any(n in txt.lower() for n in noise):
                    paras.append(txt)
                    
            full_text = "\n\n".join(paras)
            word_count = len(re.findall(r'\b\w+\b', full_text))
            
            article = {
                "id": f"eco_{int(time.time() * 1000)}",
                "url": url,
                "title": title or "The Economist Article",
                "source": "The Economist",
                "section": section,
                "standfirst": "",
                "authors": ["The Economist Staff"],
                "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "paragraphs": paras,
                "paragraph_count": len(paras),
                "word_count": word_count,
                "full_text": full_text,
                "is_paywalled": len(paras) < 3,
                "synced_via_dp": True
            }
            if len(paras) > 0:
                upsert_article(article)
            return article
        except Exception as e:
            return {
                "id": f"eco_{int(time.time() * 1000)}",
                "url": url,
                "title": "Scrape Exception",
                "source": "The Economist",
                "error": str(e),
                "paragraph_count": 0,
                "paragraphs": [],
                "full_text": "",
                "word_count": 0,
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        finally:
            if page:
                try: page.quit()
                except: pass

def scan_rss_section_dp(section_id: str = "leaders", limit: int = 10, cookie_str: Optional[str] = None) -> Dict[str, Any]:
    sec_info = next((s for s in ECONOMIST_SECTIONS if s["id"] == section_id), ECONOMIST_SECTIONS[0])
    
    with _dp_lock:
        page = None
        try:
            page = get_dp_page(cookie_str)
            sec_url = f"https://www.economist.com/{section_id}/" if section_id != "leaders" else "https://www.economist.com/leaders/"
            
            page.get(sec_url, timeout=30)
            if "just a moment" in page.title.lower() or "verify" in page.title.lower():
                page.wait(10)
                
            links = page.eles('tag:a')
            results = []
            for a in links:
                href = a.attr('href')
                text = a.text
                if href and re.search(r'economist\.com/[a-z-]+/\d{4}/\d{2}/\d{2}/', href):
                    if 'weeklyedition' not in href and 'podcasts' not in href and text and len(text.strip()) > 5:
                        results.append(href)
                        
            unique_links = list(dict.fromkeys(results))[:limit]
            
            scraped_count = 0
            for link in unique_links:
                try:
                    page.get(link, timeout=30)
                    page.wait(3) # Wait for React content!
                    
                    h1 = page.ele('tag:h1')
                    title = h1.text if h1 else page.title
                    
                    ps = page.eles('css:article p, [data-component="paragraph"] p, main p')
                    paras = []
                    noise = ['listen to this story', 'enjoy more audio', 'save time', 'to stay on top', 'subscriber-only']
                    for p in ps:
                        txt = p.text.strip()
                        if len(txt) > 20 and not any(n in txt.lower() for n in noise):
                            paras.append(txt)
                            
                    if len(paras) >= 3:
                        full_text = "\n\n".join(paras)
                        word_count = len(re.findall(r'\b\w+\b', full_text))
                        article = {
                            "id": f"eco_{int(time.time() * 1000)}",
                            "url": link,
                            "title": title or "The Economist Article",
                            "source": "The Economist",
                            "section": sec_info["name"].split()[0],
                            "standfirst": "",
                            "authors": ["The Economist Staff"],
                            "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "paragraphs": paras,
                            "paragraph_count": len(paras),
                            "word_count": word_count,
                            "full_text": full_text,
                            "is_paywalled": False,
                            "synced_via_dp": True
                        }
                        upsert_article(article)
                        scraped_count += 1
                except:
                    continue
                    
            return {
                "success": True,
                "scanned_count": len(unique_links),
                "scraped_count": scraped_count,
                "section": sec_info["name"]
            }
        except Exception as e:
            return {"success": False, "message": f"探测异常: {e}", "scanned_count": 0, "scraped_count": 0}
        finally:
            if page:
                try: page.quit()
                except: pass


def old_scrape_single_article(url: str, section: str = "Leaders", cookie_str: Optional[str] = None) -> Dict[str, Any]:
    headers = build_headers(cookie_str)
    try:
        res = cffi_requests.get(url, headers=headers, impersonate="chrome124", timeout=25)
        article = parse_economist_html(res.text, url, section)
        if article.get("paragraph_count", 0) > 0 and not article.get("security_blocked"):
            upsert_article(article)
            return article
        
        # If Cloudflare blocked or empty, fallback to reader proxy
        if article.get("security_blocked") or article.get("paragraph_count", 0) == 0:
            reader_art = scrape_via_reader_fallback(url, section)
            if reader_art and reader_art.get("paragraph_count", 0) > 0:
                upsert_article(reader_art)
                return reader_art
        return article
    except Exception as e:
        # Fallback to reader proxy
        try:
            reader_art = scrape_via_reader_fallback(url, section)
            if reader_art and reader_art.get("paragraph_count", 0) > 0:
                upsert_article(reader_art)
                return reader_art
        except Exception:
            pass
        return {
            "id": f"eco_{int(time.time() * 1000)}",
            "url": url,
            "title": "Scrape Exception",
            "source": "The Economist",
            "error": str(e),
            "paragraph_count": 0,
            "paragraphs": [],
            "full_text": "",
            "word_count": 0,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

def old_scan_rss_section(section_id: str = "leaders", limit: int = 10, cookie_str: Optional[str] = None) -> Dict[str, Any]:
    sec_info = next((s for s in ECONOMIST_SECTIONS if s["id"] == section_id), ECONOMIST_SECTIONS[0])
    rss_url = sec_info["url"]
    
    headers = build_headers(cookie_str)
    try:
        res = cffi_requests.get(rss_url, headers=headers, impersonate="chrome124", timeout=20)
        soup = BeautifulSoup(res.text, "xml")
        items = soup.find_all("item")
    except Exception as e:
        return {"success": False, "message": f"RSS 获取异常: {e}", "scanned_count": 0, "scraped_count": 0}

    scraped_count = 0
    scanned_count = len(items)
    
    for it in items[:limit]:
        link_el = it.find("link")
        if not link_el:
            continue
        link = link_el.get_text(strip=True)
        # Probe and scrape
        art = scrape_single_article(link, section=sec_info["name"].split()[0], cookie_str=cookie_str)
        if art.get("paragraph_count", 0) >= 3 and not art.get("security_blocked"):
            scraped_count += 1
        time.sleep(1.5)

    return {
        "success": True,
        "scanned_count": scanned_count,
        "scraped_count": scraped_count,
        "section": sec_info["name"]
    }

def batch_import_browser_articles(articles_data: List[Dict[str, Any]], cookie_str: Optional[str] = None) -> int:
    """Import full-text articles synced directly from user's logged-in browser."""
    if cookie_str:
        save_cookie(cookie_str)
    
    count = 0
    for raw in articles_data:
        url = raw.get("url", "").strip()
        if not url:
            continue
        
        paras = raw.get("paragraphs", [])
        if isinstance(paras, str):
            paras = [p.strip() for p in paras.split("\n\n") if p.strip()]
        
        full_text = raw.get("full_text") or "\n\n".join(paras)
        word_count = raw.get("word_count") or len(re.findall(r'\b\w+\b', full_text))

        article = {
            "id": f"eco_{int(time.time() * 1000)}_{count}",
            "url": url,
            "title": raw.get("title") or "The Economist Article",
            "source": "The Economist",
            "section": raw.get("section") or "Leaders",
            "standfirst": raw.get("standfirst") or raw.get("rubric") or "",
            "authors": raw.get("authors") or ["The Economist Staff"],
            "published_at": raw.get("published_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "paragraphs": paras,
            "paragraph_count": len(paras),
            "word_count": word_count,
            "full_text": full_text,
            "is_paywalled": False,
            "synced_from_browser": True
        }
        upsert_article(article)
        count += 1

    return count

def parse_and_import_text(content: str, default_url: str = "", default_section: str = "Leaders") -> Dict[str, Any]:
    content = content.strip()
    if not content:
        return {"success": False, "message": "内容为空"}

    # 1. Check if JSON payload (from F12 script copy)
    if (content.startswith("{") and content.endswith("}")) or (content.startswith("[") and content.endswith("]")):
        try:
            parsed_json = json.loads(content)
            if isinstance(parsed_json, dict):
                ck = parsed_json.get("cookie", "")
                if ck:
                    save_cookie(ck)
                arts = parsed_json.get("articles", [])
                if not arts and "title" in parsed_json:
                    arts = [parsed_json]
                c = batch_import_browser_articles(arts, ck)
                return {"success": True, "imported_count": c, "message": f"成功从 JSON 解析并导入 {c} 篇《经济学人》全文！"}
            elif isinstance(parsed_json, list):
                c = batch_import_browser_articles(parsed_json)
                return {"success": True, "imported_count": c, "message": f"成功从 JSON 解析并导入 {c} 篇《经济学人》全文！"}
        except Exception:
            pass

    # 2. Parse Raw Article Text
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if not lines:
        return {"success": False, "message": "无法识别有效文本内容"}

    section = default_section or "Leaders"
    title = ""
    standfirst = ""
    paras = []
    url = default_url or f"https://www.economist.com/manual/{int(time.time())}"

    idx = 0
    # First line might be Section or Section | Rubric
    if "|" in lines[0] and len(lines[0]) < 80:
        sec_parts = lines[0].split("|")
        section = sec_parts[0].strip()
        idx += 1
    elif len(lines[0]) < 35 and idx + 1 < len(lines) and len(lines[1]) > 20:
        section = lines[0]
        idx += 1

    if idx < len(lines):
        title = lines[idx]
        idx += 1

    if idx < len(lines) and len(lines[idx]) < 250 and not any(lines[idx].lower().startswith(m) for m in ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "202"]) and "min read" not in lines[idx].lower():
        standfirst = lines[idx]
        idx += 1

    noise_keywords = [
        "min read", "listen to this story", "enjoy more audio", "save time by listening",
        "the economist app", "for more coverage", "illustration:", "photograph:", "share"
    ]
    date_months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

    while idx < len(lines):
        line = lines[idx]
        idx += 1
        low = line.lower()
        if any(n in low for n in noise_keywords):
            continue
        if any(low.startswith(m) for m in date_months) and ("202" in low or "min" in low):
            continue
        if len(line) > 20:
            paras.append(line)

    if not paras:
        return {"success": False, "message": "未能从粘贴文本中识别出有效段落内容"}

    full_text = "\n\n".join(paras)
    word_count = len(re.findall(r'\b\w+\b', full_text))

    article = {
        "id": f"eco_{int(time.time() * 1000)}",
        "url": url,
        "title": title or "The Economist Article",
        "source": "The Economist",
        "section": section,
        "standfirst": standfirst,
        "authors": ["The Economist Staff"],
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "paragraphs": paras,
        "paragraph_count": len(paras),
        "word_count": word_count,
        "full_text": full_text,
        "is_paywalled": False,
        "synced_from_browser": True
    }
    upsert_article(article)
    return {
        "success": True,
        "imported_count": 1,
        "article": article,
        "message": f"成功识别并入库文章: 《{article['title']}》 ({len(paras)} 段, {word_count} 词)！"
    }


def scrape_single_article(url: str, section: str = "Leaders", cookie_str: Optional[str] = None) -> Dict[str, Any]:
    return scrape_single_article_dp(url, section, cookie_str)

def scan_rss_section(section_id: str = "leaders", limit: int = 10, cookie_str: Optional[str] = None) -> Dict[str, Any]:
    return scan_rss_section_dp(section_id, limit, cookie_str)
