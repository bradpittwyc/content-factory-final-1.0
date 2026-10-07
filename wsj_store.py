"""WSJ articles captured from a readable page in the user's browser or automated syndication."""
import hashlib
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit
import urllib.request
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

DATA = Path(__file__).parent / 'data'
STORE = DATA / 'wsj_articles.json'
QUEUE = DATA / 'wsj_columns.json'
LOCK = threading.RLock()
SECTIONS = [{'id': key, 'name': name, 'url': 'https://www.wsj.com/' + key}
            for key, name in [('tech', 'Technology 科技'), ('business', 'Business 商业'),
                              ('finance', 'Finance 金融'), ('economy', 'Economy 经济'),
                              ('world', 'World 国际'), ('opinion', 'Opinion 观点')]]
router = APIRouter(prefix='/wsj')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}


def normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or parsed.netloc not in ('www.wsj.com', 'wsj.com'):
        raise ValueError('Only HTTPS WSJ main-site URLs are accepted')
    if not re.search(r'-(?:[0-9a-f]{8}|\d{10,})$', parsed.path.rstrip('/'), re.I):
        raise ValueError('Expected a WSJ article URL, not a section or subscription page')
    return 'https://www.wsj.com' + parsed.path.rstrip('/')


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


def load_articles() -> List[Dict[str, Any]]:
    with LOCK:
        if not STORE.exists():
            return []
        try:
            items = json.loads(STORE.read_text(encoding='utf-8'))
            if not isinstance(items, list):
                return []
        except Exception:
            return []

        # 3-day (72h) retention auto-purge
        cutoff = datetime.now() - timedelta(days=3)
        kept = []
        needs_rewrite = False
        for a in items:
            dt = parse_article_datetime(a.get("published_at")) or parse_article_datetime(a.get("scraped_at"))
            if dt and dt < cutoff:
                needs_rewrite = True
                continue
            kept.append(a)

        if needs_rewrite:
            try:
                write_json(STORE, kept)
            except Exception:
                pass
        return kept


def read_queue() -> Dict[str, Any]:
    return json.loads(QUEUE.read_text(encoding='utf-8')) if QUEUE.exists() else {}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def upsert_article(art: Dict[str, Any]) -> bool:
    """Upsert an article into the WSJ article store. Returns True if newly added, False if updated."""
    with LOCK:
        items = load_articles()
        url = art.get('url')
        title = art.get('title')
        body_sha256 = art.get('body_sha256')

        idx = next((i for i, a in enumerate(items) if
                    (url and a.get('url') == url) or
                    (body_sha256 and a.get('body_sha256') == body_sha256) or
                    (title and a.get('title') == title)), None)
        if idx is not None:
            existing = items[idx]
            for k, v in art.items():
                if v is not None:
                    existing[k] = v
            items[idx] = existing
            write_json(STORE, items)
            return False
        else:
            items.insert(0, art)
            write_json(STORE, items)
            return True


def check_origin(request: Request) -> None:
    origin = request.headers.get('origin')
    if origin and not re.fullmatch(r'chrome-extension://[a-p]{32}', origin):
        raise HTTPException(403, 'Only the browser extension may submit WSJ captures')


class Block(BaseModel):
    kind: str = Field(pattern=r'^(p|li|h2|h3|blockquote)$')
    text: str = Field(max_length=30000)


class Capture(BaseModel):
    url: str = Field(max_length=2000)
    canonical_url: str | None = None
    title: str = Field(default='', max_length=1000)
    standfirst: str = Field(default='', max_length=5000)
    authors: list[str] = Field(default_factory=list, max_length=30)
    published_at: str | None = None
    body_blocks: list[Block] = Field(default_factory=list, max_length=3000)
    body_selector: str = Field(default='', max_length=500)
    takeaways: list[str] = Field(default_factory=list, max_length=30)
    blocked: bool = False
    gated: bool = False
    section: str | None = None


class Link(BaseModel):
    url: str
    title: str = ''


class Discovery(BaseModel):
    url: str
    links: list[Link] = Field(default_factory=list, max_length=3000)
    blocked: bool = False
    gated: bool = False


@router.get('/articles')
def articles():
    items = load_articles()
    return {'success': True, 'articles': items, 'total': len(items), 'sections': SECTIONS}


@router.post('/capture')
def capture(payload: Capture, request: Request):
    check_origin(request)
    try:
        url = normalize_url(payload.url)
        if payload.canonical_url and normalize_url(payload.canonical_url) != url:
            raise ValueError('Canonical URL does not match the opened article')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    stamp = datetime.now(timezone.utc).isoformat()
    with LOCK:
        write_json(DATA / 'wsj_inbox' / f'{hashlib.sha256(url.encode()).hexdigest()[:20]}.json',
                   {**payload.model_dump(), 'received_at': stamp})
        if payload.blocked or payload.gated:
            return {'saved': False, 'status': 'blocked' if payload.blocked else 'subscription_gate'}
        blocks = [block.model_dump() for block in payload.body_blocks if block.text.strip()]
        paragraphs = [block['text'].strip() for block in blocks if block['kind'] in ('p', 'li', 'blockquote')]
        text = '\n\n'.join(block['text'].strip() for block in blocks)
        words = len(text.split())
        if not payload.title.strip() or not payload.body_selector or len(paragraphs) < 4 or words < 150:
            return {'saved': False, 'status': 'insufficient_body', 'paragraph_count': len(paragraphs), 'word_count': words}
        items = load_articles()
        digest = hashlib.sha256(text.encode()).hexdigest()
        if any(a['url'] != url and a.get('body_sha256') == digest for a in items):
            return {'saved': False, 'status': 'duplicate_body'}
        if payload.section and payload.section not in {s['id'] for s in SECTIONS}:
            raise HTTPException(400, 'Unknown WSJ section')
        existing = next((a for a in items if a['url'] == url), {})
        sections = set(existing.get('sections', []))
        if payload.section:
            sections.add(payload.section)
        sections.update(key for key, links in read_queue().items() if any(link['url'] == url for link in links))
        sec = payload.section or (next(iter(sorted(sections))) if sections else 'business')
        article = {**payload.model_dump(), 'id': 'wsj_' + hashlib.sha256(url.encode()).hexdigest()[:20],
                   'url': url, 'title': payload.title.strip(),
                   'body_blocks': blocks, 'paragraphs': paragraphs, 'full_text': text,
                   'paragraph_count': len(paragraphs), 'word_count': words, 'body_sha256': digest,
                   'sections': sorted(sections) if sections else [sec], 'section': sec,
                   'source': 'The Wall Street Journal', 'scraped_at': stamp, 'capture_version': 1,
                   'status': 'body_candidate', 'full_text_reviewed': False,
                   'is_paywalled': False,
                   'takeaways_source': 'WSJ' if payload.takeaways else ''}
        write_json(STORE, [article] + [a for a in items if a['url'] != url])
    return {'saved': True, 'status': 'body_candidate', 'title': article['title'], 'word_count': words}


@router.post('/columns/{section}/discover')
def discover(section: str, payload: Discovery, request: Request):
    check_origin(request)
    expected = next((s for s in SECTIONS if s['id'] == section), None)
    if not expected or payload.url.rstrip('/') != expected['url']:
        raise HTTPException(400, 'Discovery must come from the selected WSJ section page')
    if payload.blocked or payload.gated:
        raise HTTPException(409, 'WSJ verification or subscription screen requires attention')
    links = {}
    for link in payload.links:
        try:
            url = normalize_url(link.url)
        except ValueError:
            continue
        links.setdefault(url, {'url': url, 'title': link.title})
    if not links:
        raise HTTPException(422, 'No supported WSJ article links found')
    with LOCK:
        queue = read_queue()
        queue[section] = list(links.values())
        write_json(QUEUE, queue)
    return {'count': len(links)}


@router.get('/queue/{section}')
def queue(section: str):
    if section not in {s['id'] for s in SECTIONS}:
        raise HTTPException(404, 'Unknown WSJ section')
    with LOCK:
        seen = {a['url'] for a in load_articles()}
        return {'articles': [link for link in read_queue().get(section, []) if link['url'] not in seen]}


# ---------------------------------------------------------
# Automated Syndication Scraper & Unpaywalled Full-Text Extraction
# ---------------------------------------------------------

def to_amp_url(url: str) -> str:
    """Convert Livemint article URL to its AMP unpaywalled endpoint."""
    if '/amp-' in url:
        return url
    m = re.match(r'^(https://www\.livemint\.com/[^/]+/)(.+)-(\d{10,}\.html)$', url)
    if m:
        return f"{m.group(1)}{m.group(2)}/amp-{m.group(3)}"
    return url


def parse_livemint_wsj_article(url: str) -> Optional[Dict[str, Any]]:
    """Fetch and parse a syndicated WSJ article from Livemint AMP."""
    try:
        amp_url = to_amp_url(url)
        req = urllib.request.Request(amp_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        soup = BeautifulSoup(html, 'html.parser')

        # Canonical WSJ URL
        canonical = soup.find('link', rel='canonical')
        canonical_href = canonical['href'] if canonical and 'href' in canonical.attrs else ''
        wsj_url = canonical_href if 'wsj.com' in canonical_href else url

        # Title
        h1 = soup.find('h1')
        title = h1.get_text(' ', strip=True) if h1 else ''
        if not title:
            return None

        # Standfirst / Subtitle
        standfirst = ''
        h2 = soup.find('h2')
        if h2 and len(h2.get_text(strip=True)) > 20 and 'topics' not in h2.get_text(strip=True).lower():
            standfirst = h2.get_text(' ', strip=True)
        else:
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                standfirst = meta_desc['content'].strip()

        # Authors
        authors = []
        byline_el = soup.find(class_=lambda c: c and ('author' in c.lower() or 'byline' in c.lower()))
        if byline_el:
            btext = byline_el.get_text(' ', strip=True)
            btext = re.sub(r',?\s*WSJ.*', '', btext, flags=re.I)
            btext = re.sub(r'^\s*By\s+', '', btext, flags=re.I)
            raw_authors = [a.strip() for a in re.split(r'[,&]|\band\b', btext) if a.strip()]
            for a in raw_authors:
                if not any(k in a.lower() for k in ['min read', 'ist', 'am', 'pm', 'mint', 'updated', 'published', '2026', '2025']):
                    if len(a) < 50:
                        authors.append(a)

        # Published Date
        published_at = None
        for s in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(s.get_text())
                if isinstance(data, dict) and data.get('datePublished'):
                    published_at = data['datePublished']
                    break
            except Exception:
                pass

        # Convert published_at to Beijing Time (UTC+8)
        pub_str = None
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at)
                beijing_tz = timezone(timedelta(hours=8))
                dt_bj = dt.astimezone(beijing_tz)
                pub_str = dt_bj.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                pub_str = str(published_at)[:19].replace('T', ' ')
        if not pub_str:
            pub_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Extract Paragraphs
        paras = []
        for p in soup.find_all('p'):
            text = p.get_text(' ', strip=True)
            if not text or len(text) < 25:
                continue
            if any(k in text.lower() for k in [
                'mint premium article', 'download the mint app', 'click here to read',
                'catch all the business news', 'subscribe to mint', 'stay updated with',
                'topics:', 'first published:', 'livemint.com'
            ]):
                continue
            paras.append(text)

        # Deduplicate consecutive identical paragraphs
        clean_paras = []
        for p in paras:
            if not clean_paras or clean_paras[-1] != p:
                clean_paras.append(p)

        word_count = sum(len(p.split()) for p in clean_paras)
        if len(clean_paras) < 4 or word_count < 150:
            return None

        # Infer section
        section = 'business'
        m_sec = re.search(r'wsj\.com/([a-z0-9_-]+)/', wsj_url)
        if m_sec:
            s_name = m_sec.group(1).lower()
            if s_name in ['tech', 'technology', 'tech-companies']: section = 'tech'
            elif s_name in ['finance', 'markets', 'investing', 'stocks']: section = 'finance'
            elif s_name in ['economy', 'central-banks']: section = 'economy'
            elif s_name in ['world', 'politics', 'asia', 'europe']: section = 'world'
            elif s_name in ['opinion', 'commentary', 'editorials']: section = 'opinion'
            elif s_name in ['business', 'companies', 'management']: section = 'business'
            else: section = s_name

        full_text = '\n\n'.join(clean_paras)
        digest = hashlib.sha256(full_text.encode('utf-8')).hexdigest()

        return {
            'id': 'wsj_' + hashlib.sha256(wsj_url.encode()).hexdigest()[:20],
            'url': wsj_url,
            'source_url': url,
            'title': title,
            'standfirst': standfirst or (clean_paras[0][:150] + '...' if clean_paras else ''),
            'authors': authors,
            'published_at': pub_str,
            'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'paragraphs': clean_paras,
            'paragraph_count': len(clean_paras),
            'word_count': word_count,
            'full_text': full_text,
            'body_blocks': [{'kind': 'p', 'text': p} for p in clean_paras],
            'body_sha256': digest,
            'section': section,
            'sections': [section],
            'source': 'The Wall Street Journal',
            'is_paywalled': False,
            'status': 'body_candidate',
            'full_text_reviewed': False
        }
    except Exception as e:
        print(f"Error parsing Livemint WSJ article {url}: {e}")
        return None


def scrape_single_wsj_url(url: str) -> Optional[Dict[str, Any]]:
    """Scrape a single WSJ article from Livemint syndication or direct link."""
    url = url.strip()
    if 'livemint.com' in url:
        return parse_livemint_wsj_article(url)

    # If it's a wsj.com link, check if we can find it in Livemint's syndication hub
    if 'wsj.com' in url:
        try:
            req = urllib.request.Request('https://www.livemint.com/wsj', headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                soup = BeautifulSoup(resp.read().decode('utf-8', errors='ignore'), 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if re.search(r'-\d{10,}\.html', href):
                    full_href = href if href.startswith('http') else 'https://www.livemint.com' + href
                    parsed = parse_livemint_wsj_article(full_href)
                    if parsed and (parsed['url'] == url or normalize_url(parsed['url']) == normalize_url(url)):
                        return parsed
        except Exception as e:
            print(f"Error matching WSJ URL against syndication: {e}")

    return None


def scan_wsj_syndication(limit: int = 15) -> List[Dict[str, Any]]:
    """Scan Livemint's official WSJ syndication hub and pull new unpaywalled articles."""
    existing_urls = {a.get('url') for a in load_articles()}
    existing_sources = {a.get('source_url') for a in load_articles() if a.get('source_url')}
    new_articles = []

    try:
        req = urllib.request.Request('https://www.livemint.com/wsj', headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            soup = BeautifulSoup(resp.read().decode('utf-8', errors='ignore'), 'html.parser')

        candidates = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if re.search(r'-\d{10,}\.html', href):
                full_href = href if href.startswith('http') else 'https://www.livemint.com' + href
                if full_href not in existing_sources and full_href not in candidates:
                    candidates.append(full_href)

        print(f"[WSJ Syndication] Found {len(candidates)} candidate articles on /wsj")
        for u in candidates[:limit]:
            art = parse_livemint_wsj_article(u)
            if art:
                if art['url'] not in existing_urls:
                    upsert_article(art)
                    existing_urls.add(art['url'])
                    new_articles.append(art)
                    print(f"  + Added WSJ: {art['title'][:45]} ({art['paragraph_count']} paras, {art['word_count']} words)")
    except Exception as e:
        print(f"Error during WSJ syndication scan: {e}")

    return new_articles


class WsjScanRequest(BaseModel):
    limit: Optional[int] = 15


class WsjSingleScrapeRequest(BaseModel):
    url: str


class WsjPasteImportRequest(BaseModel):
    title: str
    full_text: str
    url: Optional[str] = None
    standfirst: Optional[str] = None
    authors: Optional[List[str]] = None
    section: Optional[str] = 'business'


@router.post('/scan')
def scan_endpoint(req: WsjScanRequest = WsjScanRequest()):
    try:
        new_arts = scan_wsj_syndication(limit=req.limit or 15)
        all_articles = load_articles()
        return {
            'success': True,
            'new_count': len(new_arts),
            'articles': all_articles,
            'total': len(all_articles)
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


@router.post('/scrape-single')
def scrape_single_endpoint(req: WsjSingleScrapeRequest):
    try:
        art = scrape_single_wsj_url(req.url)
        if not art:
            raise HTTPException(404, '未能解析该链接或该文章不在全球免登录分发源中')
        upsert_article(art)
        return {
            'success': True,
            'article': art
        }
    except HTTPException:
        raise
    except Exception as e:
        return {'success': False, 'error': str(e)}


@router.post('/paste-import')
def paste_import_endpoint(req: WsjPasteImportRequest):
    try:
        paragraphs = [p.strip() for p in req.full_text.split('\n') if len(p.strip()) > 20]
        word_count = sum(len(p.split()) for p in paragraphs)
        if len(paragraphs) < 3 or word_count < 100:
            raise HTTPException(400, '正文段落过少或词数不足，无法作为长文入库')

        url = req.url.strip() if req.url else f"https://www.wsj.com/{req.section or 'business'}/imported-{hashlib.sha256(req.title.encode()).hexdigest()[:8]}"
        digest = hashlib.sha256(req.full_text.encode('utf-8')).hexdigest()

        art = {
            'id': 'wsj_' + hashlib.sha256(url.encode()).hexdigest()[:20],
            'url': url,
            'title': req.title.strip(),
            'standfirst': req.standfirst or (paragraphs[0][:150] + '...' if paragraphs else ''),
            'authors': req.authors or ['The Wall Street Journal'],
            'published_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'paragraphs': paragraphs,
            'paragraph_count': len(paragraphs),
            'word_count': word_count,
            'full_text': '\n\n'.join(paragraphs),
            'body_blocks': [{'kind': 'p', 'text': p} for p in paragraphs],
            'body_sha256': digest,
            'section': req.section or 'business',
            'sections': [req.section or 'business'],
            'source': 'The Wall Street Journal',
            'is_paywalled': False,
            'status': 'body_candidate',
            'full_text_reviewed': True
        }
        upsert_article(art)
        return {
            'success': True,
            'article': art
        }
    except HTTPException:
        raise
    except Exception as e:
        return {'success': False, 'error': str(e)}
