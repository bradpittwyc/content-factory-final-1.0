"""WSJ articles captured from a readable page in the user's browser."""
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

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


def normalize_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or parsed.netloc not in ('www.wsj.com', 'wsj.com'):
        raise ValueError('Only HTTPS WSJ main-site URLs are accepted')
    if not re.search(r'-(?:[0-9a-f]{8}|\d{10,})$', parsed.path.rstrip('/'), re.I):
        raise ValueError('Expected a WSJ article URL, not a section or subscription page')
    return 'https://www.wsj.com' + parsed.path.rstrip('/')


def load_articles():
    with LOCK:
        return json.loads(STORE.read_text(encoding='utf-8')) if STORE.exists() else []


def read_queue():
    return json.loads(QUEUE.read_text(encoding='utf-8')) if QUEUE.exists() else {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def check_origin(request):
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
        article = {**payload.model_dump(), 'url': url, 'title': payload.title.strip(),
                   'body_blocks': blocks, 'paragraphs': paragraphs, 'full_text': text,
                   'paragraph_count': len(paragraphs), 'word_count': words, 'body_sha256': digest,
                   'sections': sorted(sections), 'section': payload.section or next(iter(sorted(sections)), 'WSJ'),
                   'source': 'The Wall Street Journal', 'scraped_at': stamp, 'capture_version': 1,
                   'status': 'body_candidate', 'full_text_reviewed': False,
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
