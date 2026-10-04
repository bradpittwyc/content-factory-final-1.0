"""Bounded BNN Bloomberg crawl with checkpoints and optional store import."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import bloomberg_store as store

BASE = "https://www.bnnbloomberg.ca"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def article_url(value):
    url = urljoin(BASE, value)
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "www.bnnbloomberg.ca":
        return None
    if not re.search(r"/\d{4}/\d{2}/\d{2}/", parts.path):
        return None
    if parts.path.startswith(("/video/", "/faq/", "/press-releases/", "/investment-trends/")):
        return None
    return BASE + parts.path.rstrip("/") + "/"


class Fetcher:
    def __init__(self, delay):
        self.delay = delay
        self.last_request = 0

    def get(self, url):
        time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = urllib.request.Request(url, headers=store.HEADERS)
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-articles", type=int, default=100, help="Maximum new article requests")
    parser.add_argument("--days", type=int, default=7, help="Daily sitemap discovery window")
    parser.add_argument("--delay", type=float, default=1.0, help="Minimum seconds between request starts")
    parser.add_argument("--import", dest="import_store", action="store_true", help="Import accepted stories into the console store")
    args = parser.parse_args()
    if args.max_articles < 1 or not 1 <= args.days <= 31 or args.delay < 0.5:
        parser.error("max-articles must be positive, days must be 1..31, delay must be >= 0.5")

    started = datetime.now(timezone.utc)
    run_dir = Path(__file__).parent / "data" / "bloomberg_runs" / started.strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(parents=True)
    # Read directly: discovery must not invoke the store's retention cleanup.
    initial = json.loads(store.BLOOMBERG_ARTICLES_FILE.read_text(encoding="utf-8")) if store.BLOOMBERG_ARTICLES_FILE.exists() else []
    if not isinstance(initial, list):
        raise ValueError("Bloomberg store must be a JSON array")
    (run_dir / "store_before.json").write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding="utf-8")
    existing = {article_url(a.get("url", "")) for a in initial}
    titles = {a.get("title") for a in initial}
    candidates = {}
    accepted = []
    report = {"started_at": started.isoformat(), "settings": vars(args), "existing_count": len(initial), "discovery": [], "results": []}
    fetcher = Fetcher(args.delay)

    def checkpoint():
        (run_dir / "articles.json").write_text(json.dumps(accepted, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def discover(url, label, sitemap=False):
        try:
            text = fetcher.get(url)
            if sitemap:
                root = ET.fromstring(text)
                links = [entry.findtext("s:loc", namespaces=NS) for entry in root.findall("s:url", NS)]
            else:
                links = [a["href"] for a in BeautifulSoup(text, "html.parser").find_all("a", href=True)]
            count = 0
            for link in links:
                normalized = article_url(link) if link else None
                if normalized and normalized not in candidates:
                    candidates[normalized] = label
                    count += 1
            report["discovery"].append({"url": url, "new_candidates": count})
            print(f"DISCOVERY {label}: +{count} (total {len(candidates)})", flush=True)
        except urllib.error.HTTPError as error:
            report["discovery"].append({"url": url, "http_status": error.code})
            if error.code in (403, 429):
                raise
        except (OSError, ET.ParseError) as error:
            report["discovery"].append({"url": url, "error": str(error)})

    stopped = None
    try:
        for label, url in store.SECTIONS:
            discover(url, label)
        today = datetime.now().date()
        for offset in range(args.days):
            suffix = "latest" if offset == 0 else (today - timedelta(days=offset)).isoformat()
            discover(f"{BASE}/arc/outboundfeeds/sitemap/{suffix}/?outputType=xml", "Sitemap", True)
            if sum(url not in existing for url in candidates) >= args.max_articles:
                break
        report["candidate_count"] = len(candidates)
        report["already_stored"] = sum(url in existing for url in candidates)
        checkpoint()
        for url, label in candidates.items():
            if url in existing:
                continue
            if len(report["results"]) >= args.max_articles:
                break
            row = {"url": url}
            try:
                article = store.parse_bloomberg_html(fetcher.get(url), url, label)
                if article is None:
                    row["status"] = "rejected_body_or_quality"
                elif article["title"] in titles:
                    row["status"] = "duplicate_title"
                else:
                    accepted.append(article)
                    titles.add(article["title"])
                    row.update(status="accepted", title=article["title"], word_count=article["word_count"], paragraph_count=article["paragraph_count"], published_at=article["published_at"])
            except urllib.error.HTTPError as error:
                row.update(status="http_error", http_status=error.code)
                if error.code in (403, 429):
                    stopped = f"HTTP {error.code}"
            except OSError as error:
                row.update(status="network_error", error=str(error))
            report["results"].append(row)
            checkpoint()
            print(f"[{len(report['results'])}/{args.max_articles}] {row['status']} {url}", flush=True)
            if stopped:
                break
    except urllib.error.HTTPError as error:
        stopped = f"Discovery HTTP {error.code}"
    except KeyboardInterrupt:
        stopped = "Interrupted"
    finally:
        report.update(accepted_count=len(accepted), attempted_count=len(report["results"]), stopped_reason=stopped, finished_at=datetime.now(timezone.utc).isoformat())
        if args.import_store and accepted:
            # Re-read to preserve articles saved by another process during the crawl.
            current = json.loads(store.BLOOMBERG_ARTICLES_FILE.read_text(encoding="utf-8")) if store.BLOOMBERG_ARTICLES_FILE.exists() else []
            current_urls = {article_url(a.get("url", "")) for a in current}
            current_titles = {a.get("title") for a in current}
            additions = [a for a in accepted if a["url"] not in current_urls and a["title"] not in current_titles]
            store.save_bloomberg_articles(list(reversed(additions)) + current)
            report["imported_count"] = len(additions)
        checkpoint()
        print(json.dumps({k: report.get(k) for k in ("candidate_count", "already_stored", "attempted_count", "accepted_count", "imported_count", "stopped_reason")}, ensure_ascii=False), flush=True)
        print(f"REPORT {run_dir / 'report.json'}", flush=True)
    return 1 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
