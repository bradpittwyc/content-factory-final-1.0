"""Receive Bloomberg.com article DOM from the user's logged-in browser."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
from bloomberg_tech_scheduler import Scheduler
from bloomberg_columns import DEFAULT_COLUMNS, load_columns, validate_column

DATA = Path(__file__).parent / "data"
STORE = DATA / "bloomberg_main_articles.json"
INBOX = DATA / "bloomberg_main_inbox"
COLUMN_DIR = DATA / "bloomberg_main_columns"
COLUMNS = DEFAULT_COLUMNS
STORE_LOCK = threading.Lock()
SCHEDULER = Scheduler(DATA / 'bloomberg_tech_scheduler.sqlite3')
app = FastAPI(title="Bloomberg main-site browser bridge")
from wsj_store import router as wsj_router
app.include_router(wsj_router)
app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://[a-p]{32}", allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class BodyBlock(BaseModel):
    kind: Literal["p", "li", "h2", "h3", "blockquote"]
    text: str
    is_related: bool = False


class Capture(BaseModel):
    url: str
    canonical_url: str = ''
    title: str = ""
    page_title: str = ""
    paragraphs: list[str] = Field(default_factory=list)
    body_blocks: list[BodyBlock] = Field(default_factory=list)
    capture_version: int = 1
    published_at: str | None = None
    authors: list[str] = Field(default_factory=list)
    blocked: bool = False
    gated: bool = False
    body_selector: str = ""
    diagnostics: list[dict] = Field(default_factory=list)
    column: str | None = None
    automation_attempt_id: str | None = None
    takeaways: list[str] = Field(default_factory=list, max_length=20)
    takeaways_source: str = ''
    takeaways_status: Literal['unknown', 'captured', 'not_present', 'collapsed_or_empty'] = 'unknown'
    takeaways_capture_version: int = 0


class ColumnLink(BaseModel):
    url: str
    title: str = ""


class ColumnDiscovery(BaseModel):
    url: str
    page_title: str = ""
    blocked: bool = False
    gated: bool = False
    links: list[ColumnLink] = Field(default_factory=list, max_length=5000)


def normalize_main_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "www.bloomberg.com":
        raise ValueError("Only https://www.bloomberg.com articles are accepted")
    if not parsed.path.startswith(("/news/articles/", "/opinion/articles/", "/news/newsletters/", "/opinion/newsletters/", "/news/features/", "/features/")):
        raise ValueError("URL is not a supported Bloomberg main-site article")
    return "https://www.bloomberg.com" + parsed.path.rstrip("/")


def cleaned_blocks(capture):
    blocks = capture.body_blocks or [BodyBlock(kind="p", text=p) for p in capture.paragraphs]
    return [block.model_copy(update={"text": block.text.strip()}) for block in blocks
            if block.text.strip() and not block.is_related
            and not re.match(r"^(?:Read More|Read more|Related|Also Read)\s*:", block.text.strip())]


def validate_capture(capture):
    url = normalize_main_url(capture.url)
    if capture.blocked:
        return url, "blocked", []
    if capture.gated:
        return url, "subscription_gate", []
    if capture.canonical_url and normalize_main_url(capture.canonical_url) != url:
        return url, 'needs_body_inspection', []
    blocks = cleaned_blocks(capture)
    paragraphs = [block.text for block in blocks]
    words = sum(len(p.split()) for p in paragraphs)
    if not capture.title.strip() or not capture.body_selector or sum(block.kind == "p" for block in blocks) < 4 or words < 150:
        return url, "needs_body_inspection", paragraphs
    return url, "body_candidate", paragraphs


@app.get("/status")
def status():
    articles = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
    return {"source": "www.bloomberg.com", "article_candidates": len(articles), "automation_protocol": 1, "note": "DOM body candidates require initial full-text review"}


def column_candidates(column):
    get_column(column)
    path = COLUMN_DIR / f"{column}.json"
    return json.loads(path.read_text(encoding="utf-8")).get("articles", []) if path.exists() else []


def column_catalog():
    return load_columns(DATA / 'bloomberg_main_column_settings.json')


def get_column(column):
    catalog = column_catalog()
    if column not in catalog:
        raise HTTPException(404, 'Unknown Bloomberg column')
    return catalog[column]


class ColumnSettings(BaseModel):
    id: str | None = None
    name: str
    url: str
    enabled: bool = False


@app.get('/columns')
def list_columns():
    return {'columns': list(column_catalog().values())}


@app.post('/columns/configure')
def configure_column(payload: ColumnSettings, request: Request):
    check_control_origin(request)
    try:
        item = validate_column(payload.model_dump())
        if item['id'] == 'ai-today' and item['enabled'] and not column_candidates('ai-today'):
            raise ValueError('请先手动试抓 AI Today，确认入口有明确的 newsletter 文章链接，再启用自动采集')
        with STORE_LOCK:
            catalog = column_catalog()
            previous = catalog.get(item['id'])
            if previous and previous['url'] != item['url']:
                raise ValueError('Existing column URLs are immutable; add a new column instead')
            catalog[item['id']] = item
            path = DATA / 'bloomberg_main_column_settings.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(list(catalog.values()), ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(path)
        return {'columns': list(catalog.values())}
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.post("/columns/{column}/discover")
def discover_column(column: str, discovery: ColumnDiscovery):
    expected = get_column(column)['url']
    parsed = urlsplit(discovery.url)
    paths = {urlsplit(expected).path.rstrip('/')}
    # The logged-in browser redirects the legacy Finance entry to /finance.
    if column == 'finance' and paths.intersection({'/finance', '/industries/finance'}):
        paths.update({'/finance', '/industries/finance'})
    if column == 'ai-today':
        paths.add('/standalone/ai-today')
    if parsed.scheme != "https" or parsed.netloc != "www.bloomberg.com" or parsed.path.rstrip("/") not in paths:
        raise HTTPException(status_code=400, detail="Column discovery must come from its configured entry page")
    if discovery.blocked:
        raise HTTPException(status_code=409, detail="Tech page returned a browser verification screen")
    articles = {}
    for link in discovery.links:
        if column == 'ai-today' and ('/newsletters/' not in urlsplit(link.url).path or not re.search(r'latest edition|read (the )?latest|最新一期|ai today', link.title, re.I)):
            continue
        try:
            url = normalize_main_url(link.url)
        except ValueError:
            continue
        if url not in articles:
            articles[url] = {"url": url, "title": link.title, "column": column, "column_url": expected}
    if not articles:
        raise HTTPException(status_code=422, detail=f"No supported article links found in the {column} page")
    payload = {"column": column, "source_url": expected, "discovered_at": datetime.now(timezone.utc).isoformat(), "articles": list(articles.values())}
    with STORE_LOCK:
        COLUMN_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = COLUMN_DIR / f'{column}.json'
        temporary_snapshot = snapshot.with_suffix('.tmp')
        temporary_snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary_snapshot.replace(snapshot)
        stored = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
        changed = False
        for article in stored:
            if article["url"] in articles:
                memberships = set(article.get("columns", []))
                memberships.add(column)
                article["columns"] = sorted(memberships)
                article["column_sources"] = {**article.get("column_sources", {}), column: expected}
                changed = True
        if changed:
            temporary = STORE.with_suffix(".tmp")
            temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(STORE)
    return {"column": column, "candidate_count": len(articles), "source_url": expected}


@app.get("/queue")
def queue(column: str | None = None):
    if column:
        candidates = column_candidates(column)
    else:
        path = DATA / "bloomberg_main_probe" / "candidates.json"
        candidates = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    stored = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
    # Refresh older paragraph-only captures before moving to new articles.
    seen = {a["url"] for a in stored if a.get("capture_version", 1) >= 2 and not a.get("needs_recapture")}
    result = []
    for candidate in candidates:
        try:
            url = normalize_main_url(candidate["url"])
        except ValueError:
            continue
        if url not in seen:
            result.append({**candidate, "url": url})
    return {"articles": result, "column": column, "candidate_count": len(candidates)}


@app.post("/capture")
def capture_article(capture: Capture):
    try:
        url, state, paragraphs = validate_capture(capture)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if capture.column and url not in {a["url"] for a in column_candidates(capture.column)}:
        raise HTTPException(status_code=400, detail="Article is not in the discovered column queue")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    article_id = "bloomberg_" + hashlib.sha256(url.encode()).hexdigest()[:20]
    INBOX.mkdir(parents=True, exist_ok=True)
    raw = capture.model_dump()
    raw.update(status=state, captured_at=now)
    (INBOX / f"{article_id}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    if state != "body_candidate":
        return {"status": state, "saved": False, "diagnostics": capture.diagnostics}
    article = {
        "id": article_id, "url": url, "title": capture.title.strip(),
        "published_at": capture.published_at, "authors": capture.authors,
        "paragraphs": paragraphs,
        "paragraph_count": sum(block.kind == "p" for block in cleaned_blocks(capture)),
        "body_blocks": [block.model_dump() for block in cleaned_blocks(capture)],
        "body_block_count": len(paragraphs), "capture_version": capture.capture_version,
        "word_count": sum(len(p.split()) for p in paragraphs), "scraped_at": now,
        "source": "Bloomberg", "access_method": "logged-in browser DOM",
        "body_selector": capture.body_selector, "full_text_reviewed": False,
        "automation_attempt_id": capture.automation_attempt_id,
        "takeaways": [item.strip() for item in capture.takeaways if item.strip()],
        "takeaways_source": capture.takeaways_source,
        "takeaways_status": capture.takeaways_status,
        "takeaways_capture_version": capture.takeaways_capture_version,
    }
    with STORE_LOCK:
        articles = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
        duplicates = [a for a in articles if a["url"] != url and a.get("paragraphs") == paragraphs]
        if duplicates:
            raw.update(status="duplicate_body", duplicate_urls=[a["url"] for a in duplicates])
            (INBOX / f"{article_id}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"status": "duplicate_body", "saved": False}
        previous = next((a for a in articles if a["url"] == url), {})
        if not capture.takeaways_capture_version:
            for field in ('takeaways', 'takeaways_source', 'takeaways_status', 'takeaways_capture_version'):
                if field in previous:
                    article[field] = previous[field]
        columns = set(previous.get("columns", []))
        if capture.column:
            columns.add(capture.column)
        catalog = column_catalog()
        for column in catalog:
            if any(candidate.get('url') == url for candidate in column_candidates(column)):
                columns.add(column)
        article["columns"] = sorted(columns)
        article["column_sources"] = {c: catalog[c]['url'] for c in columns if c in catalog}
        articles = [a for a in articles if a["url"] != url]
        articles.insert(0, article)
        temporary = STORE.with_suffix(".tmp")
        temporary.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(STORE)
    return {"status": state, "saved": True, "paragraph_count": article["paragraph_count"], "word_count": article["word_count"], "title": article["title"], "takeaways_count": len(article['takeaways'])}


class AutomationRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    run_id: str | None = None
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=2, le=1440)
    immediate: bool = False
    column: str | None = None
    discovery: ColumnDiscovery | None = None
    capture: Capture | None = None
    error: Literal['timeout', 'network_error', 'tab_closed', 'blocked', 'subscription_gate'] | None = None
    error_detail: str | None = Field(default=None, max_length=1500)


def check_control_origin(request):
    origin = request.headers.get('origin')
    if origin and not re.fullmatch(r'chrome-extension://[a-p]{32}', origin):
        raise HTTPException(403, 'Only the local extension may control automation')


def utc_date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def purge_automation_expired():
    """Prune known UTC publication dates; keep ambiguous legacy dates for migration."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    with STORE_LOCK:
        stored = json.loads(STORE.read_text(encoding='utf-8')) if STORE.exists() else []
        kept = [a for a in stored if not utc_date(a.get('published_at')) or utc_date(a.get('published_at')) >= cutoff]
        if kept != stored:
            temporary = STORE.with_suffix('.tmp')
            temporary.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(STORE)
        for directory in (INBOX, DATA / 'bloomberg_main_quarantine'):
            if directory.exists():
                for path in directory.glob('*.json'):
                    if path.stat().st_mtime < cutoff.timestamp():
                        path.unlink()


@app.get('/automation/bloomberg/status')
@app.get('/automation/tech/status')
def automation_status():
    return {**SCHEDULER.status(), 'columns': list(column_catalog().values())}


@app.post('/automation/bloomberg/{action}')
@app.post('/automation/tech/{action}')
def automation_action(action: Literal['settings', 'tick', 'discovery', 'result'], payload: AutomationRequest, request: Request):
    check_control_origin(request)
    try:
        if action == 'settings':
            if payload.enabled is None:
                raise ValueError('enabled is required')
            return SCHEDULER.configure(payload.enabled, interval_minutes=payload.interval_minutes)
        if action == 'tick':
            return SCHEDULER.tick(payload.owner, payload.immediate, columns=list(column_catalog().values()), column=payload.column)
        if not payload.run_id:
            raise ValueError('run_id is required')
        if action == 'discovery':
            if not payload.discovery:
                raise ValueError('discovery is required')
            if payload.discovery.blocked or payload.discovery.gated:
                return SCHEDULER.finish(payload.run_id, payload.owner, lambda _: {'status': 'blocked' if payload.discovery.blocked else 'subscription_gate', 'saved': False})
            with SCHEDULER.transaction() as db:
                run = SCHEDULER.active(db, payload.run_id, payload.owner, 'discover', time.time())
                column = run['column_id']
            purge_automation_expired()
            discover_column(column, payload.discovery)
            stored = json.loads(STORE.read_text(encoding='utf-8')) if STORE.exists() else []
            seen = [a['url'] for a in stored if a.get('capture_version', 1) >= 2 and not a.get('needs_recapture')]
            return SCHEDULER.discover(payload.run_id, payload.owner,
                                      [a['url'] for a in column_candidates(column)], seen)

        def save(run):
            if payload.error:
                return {'status': payload.error, 'saved': False, 'stage': run['phase'],
                        'detail': payload.error_detail or 'Legacy client did not provide error details'}
            capture = payload.capture
            if not capture or run['phase'] != 'article' or normalize_main_url(capture.url) != run['url']:
                raise ValueError('Capture does not match the claimed article')
            if capture.blocked or capture.gated:
                return {'status': 'blocked' if capture.blocked else 'subscription_gate', 'saved': False}
            published = utc_date(capture.published_at)
            if not published:
                return {'status': 'missing_date', 'saved': False}
            if published < datetime.now(timezone.utc) - timedelta(hours=72):
                return {'status': 'expired', 'saved': False}
            if published > datetime.now(timezone.utc) + timedelta(minutes=10):
                return {'status': 'invalid_date', 'saved': False}
            # Recover a crash between the JSON write and the SQLite receipt commit.
            stored = json.loads(STORE.read_text(encoding='utf-8')) if STORE.exists() else []
            existing = next((a for a in stored if a.get('automation_attempt_id') == run['id']), None)
            if existing:
                return {'status': 'body_candidate', 'saved': True, 'title': existing['title'],
                        'takeaways_count': len(existing.get('takeaways', []))}
            result = capture_article(capture.model_copy(update={'column': run['column_id'], 'automation_attempt_id': run['id']}))
            if not result.get('saved'):
                result.update(stage='article', url=capture.url, title=capture.title,
                              paragraph_count=len(capture.paragraphs),
                              body_selector=capture.body_selector,
                              detail='正文容器未识别或正文不足，需核验页面模板' if result.get('status') == 'needs_body_inspection' else result.get('status'))
            purge_automation_expired()
            return result

        return SCHEDULER.finish(payload.run_id, payload.owner, save)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8011, log_level="warning")
