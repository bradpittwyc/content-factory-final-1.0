"""Receive Bloomberg.com article DOM from the user's logged-in browser."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

DATA = Path(__file__).parent / "data"
STORE = DATA / "bloomberg_main_articles.json"
INBOX = DATA / "bloomberg_main_inbox"
COLUMN_DIR = DATA / "bloomberg_main_columns"
COLUMNS = {"tech": {"name": "Technology", "url": "https://www.bloomberg.com/technology"}}
STORE_LOCK = threading.Lock()
app = FastAPI(title="Bloomberg main-site browser bridge")
app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://[a-p]{32}", allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class BodyBlock(BaseModel):
    kind: Literal["p", "li", "h2", "h3", "blockquote"]
    text: str
    is_related: bool = False


class Capture(BaseModel):
    url: str
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
    column: Literal["tech"] | None = None


class ColumnLink(BaseModel):
    url: str
    title: str = ""


class ColumnDiscovery(BaseModel):
    url: str
    page_title: str = ""
    blocked: bool = False
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
    blocks = cleaned_blocks(capture)
    paragraphs = [block.text for block in blocks]
    words = sum(len(p.split()) for p in paragraphs)
    if not capture.title.strip() or not capture.body_selector or sum(block.kind == "p" for block in blocks) < 4 or words < 150:
        return url, "needs_body_inspection", paragraphs
    return url, "body_candidate", paragraphs


@app.get("/status")
def status():
    articles = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
    return {"source": "www.bloomberg.com", "article_candidates": len(articles), "note": "DOM body candidates require initial full-text review"}


def column_candidates(column):
    path = COLUMN_DIR / f"{column}.json"
    return json.loads(path.read_text(encoding="utf-8")).get("articles", []) if path.exists() else []


@app.post("/columns/{column}/discover")
def discover_column(column: Literal["tech"], discovery: ColumnDiscovery):
    expected = COLUMNS[column]["url"]
    parsed = urlsplit(discovery.url)
    if parsed.scheme != "https" or parsed.hostname != "www.bloomberg.com" or parsed.path.rstrip("/") != "/technology":
        raise HTTPException(status_code=400, detail="Tech discovery must come from the Technology page")
    if discovery.blocked:
        raise HTTPException(status_code=409, detail="Tech page returned a browser verification screen")
    articles = {}
    for link in discovery.links:
        try:
            url = normalize_main_url(link.url)
        except ValueError:
            continue
        if url not in articles:
            articles[url] = {"url": url, "title": link.title, "column": column, "column_url": expected}
    if not articles:
        raise HTTPException(status_code=422, detail="No supported article links found in the Tech page")
    payload = {"column": column, "source_url": expected, "discovered_at": datetime.now(timezone.utc).isoformat(), "articles": list(articles.values())}
    COLUMN_DIR.mkdir(parents=True, exist_ok=True)
    (COLUMN_DIR / f"{column}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with STORE_LOCK:
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
def queue(column: Literal["tech"] | None = None):
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
    }
    with STORE_LOCK:
        articles = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
        duplicates = [a for a in articles if a["url"] != url and a.get("paragraphs") == paragraphs]
        if duplicates:
            raw.update(status="duplicate_body", duplicate_urls=[a["url"] for a in duplicates])
            (INBOX / f"{article_id}.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"status": "duplicate_body", "saved": False}
        previous = next((a for a in articles if a["url"] == url), {})
        columns = set(previous.get("columns", []))
        if capture.column:
            columns.add(capture.column)
        article["columns"] = sorted(columns)
        article["column_sources"] = {c: COLUMNS[c]["url"] for c in columns if c in COLUMNS}
        articles = [a for a in articles if a["url"] != url]
        articles.insert(0, article)
        temporary = STORE.with_suffix(".tmp")
        temporary.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(STORE)
    return {"status": state, "saved": True, "paragraph_count": article["paragraph_count"], "word_count": article["word_count"], "title": article["title"]}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8011, log_level="warning")
