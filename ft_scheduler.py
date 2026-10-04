# -*- coding: utf-8 -*-
"""
FT Automated Drip-Feed Scheduler (FT 滴灌式防风控定时计划任务)
Strategy:
  1. Only 1 article per hour (configurable, default 60 mins).
  2. Automatic section rotation (Tech -> Markets -> Companies -> World -> Home).
  3. Pre-request randomized delay (jitter) to mimic authentic human reading.
  4. Automatic deduplication against data/ft_articles.json.
  5. Circuit Breaker: If 403 / Security Verification is triggered, auto-cooldown for 2 hours.
"""
import os
import time
import json
import random
import asyncio
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

import ft_store

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "ft_scheduler_state.json"

SECTIONS_ROTATION = ["technology", "markets", "companies", "world", "home"]

DEFAULT_STATE = {
    "enabled": True,
    "interval_minutes": 60,
    "current_section_idx": 0,
    "last_run": None,
    "next_run": None,
    "total_scraped": 0,
    "last_title": "",
    "last_status": "计划任务已就绪 (每小时自动采集 1 篇)",
    "cooldown_until": None,
    "logs": []
}

_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()

def load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        save_state(DEFAULT_STATE)
        return dict(DEFAULT_STATE)
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # merge with default
        return {**DEFAULT_STATE, **data}
    except Exception:
        return dict(DEFAULT_STATE)

def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def append_log(msg: str) -> None:
    state = load_state()
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    logs = state.get("logs", [])
    logs.insert(0, log_entry)
    state["logs"] = logs[:20]  # keep latest 20 logs
    state["last_status"] = msg
    save_state(state)
    try:
        print(f"[FT-Scheduler] {log_entry}")
    except Exception:
        pass


def execute_single_drip_scrape(ignore_cooldown: bool = False) -> Dict[str, Any]:
    """Execute a single article fetch safely."""
    state = load_state()
    
    # Check cooldown (bypassed when ignore_cooldown=True for user manual trigger)
    if not ignore_cooldown and state.get("cooldown_until"):
        try:
            cd_time = datetime.fromisoformat(state["cooldown_until"])
            if datetime.now() < cd_time:
                remaining_mins = int((cd_time - datetime.now()).total_seconds() / 60)
                msg = f"⏳ 处于安全熔断冷却保护中，还剩 {remaining_mins} 分钟，跳过本次自动调度"
                append_log(msg)
                return {"success": False, "reason": "in_cooldown", "message": msg}
            else:
                state["cooldown_until"] = None
                save_state(state)
                append_log("🛡️ 安全熔断冷却期结束，恢复正常抓取检测")
        except Exception:
            state["cooldown_until"] = None
            save_state(state)


    # 1. Rotate section
    sec_idx = state.get("current_section_idx", 0) % len(SECTIONS_ROTATION)
    target_section = SECTIONS_ROTATION[sec_idx]
    state["current_section_idx"] = (sec_idx + 1) % len(SECTIONS_ROTATION)
    save_state(state)

    append_log(f"🔍 检查版块 【{target_section}】 的最新刊源...")

    # 2. Fetch section RSS
    existing_articles = ft_store.load_all_articles()
    existing_urls = {a.get("url") for a in existing_articles}
    existing_titles = {a.get("title") for a in existing_articles}

    try:
        rss_items = asyncio.run(ft_store.fetch_section_rss_items(target_section, limit=10))
    except Exception as e:
        append_log(f"❌ 获取 RSS 列表失败: {e}")
        return {"success": False, "error": str(e)}

    # Find the first candidate that hasn't been scraped yet
    candidate = None
    for it in rss_items:
        if it["url"] not in existing_urls and it["title"] not in existing_titles:
            candidate = it
            break

    if not candidate:
        append_log(f"ℹ️ 版块 【{target_section}】 暂无新文章，下次调度将轮换下一版块")
        return {"success": True, "message": "no_new_articles"}

    # 3. Safe randomized jitter
    jitter_delay = random.uniform(3.0, 7.0)
    append_log(f"🎯 选定文章: 《{candidate['title'][:35]}...》，拟人化随机等待 {jitter_delay:.1f} 秒...")
    time.sleep(jitter_delay)

    # 4. Scrape single article
    article = ft_store.scrape_single_article(candidate["url"], section=candidate.get("section", target_section))
    
    # 5. Check if blocked
    if article.get("security_blocked"):
        # Trigger 2-hour circuit breaker!
        cooldown_time = datetime.now() + timedelta(hours=2)
        state["cooldown_until"] = cooldown_time.isoformat()
        state["next_run"] = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        save_state(state)
        msg = "⚠️ 触发 FT 安全验证拦截 (Cloudflare 403)！已自动开启 2 小时安全熔断休眠保护"
        append_log(msg)
        return {"success": False, "reason": "blocked", "message": msg}

    if article.get("paragraph_count", 0) < 3:
        append_log(f"⚠️ 文章正文段落过少 ({article.get('paragraph_count', 0)} 段)，放弃入库保护质量")
        return {"success": False, "reason": "too_short"}

    # 6. Save article
    ft_store.upsert_article(article)
    state = load_state()
    state["total_scraped"] = state.get("total_scraped", 0) + 1
    state["last_title"] = article.get("title", "")
    state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Schedule next run (60 mins + random 1-5 mins jitter)
    interval = state.get("interval_minutes", 60)
    next_delay = interval * 60 + random.randint(60, 300)
    state["next_run"] = (datetime.now() + timedelta(seconds=next_delay)).strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)

    append_log(f"✅ 成功入库 1 篇深度文章: 《{article.get('title', '')[:35]}》 ({article.get('paragraph_count')} 段 · {article.get('word_count')} 词)")
    return {"success": True, "article": article}

def _scheduler_worker():
    """Background worker loop that runs every minute to check if it's time to scrape."""
    print("[FT-Scheduler] Background worker thread started.")
    while not _stop_event.is_set():
        try:
            state = load_state()
            if state.get("enabled", True):
                next_run_str = state.get("next_run")
                should_run = False
                if not next_run_str:
                    should_run = True
                else:
                    try:
                        next_dt = datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
                        if datetime.now() >= next_dt:
                            should_run = True
                    except Exception:
                        should_run = True

                if should_run:
                    execute_single_drip_scrape()
        except Exception as e:
            print(f"[FT-Scheduler] Worker exception: {e}")

        # Sleep 30 seconds before next tick
        _stop_event.wait(30)

def start_scheduler():
    global _scheduler_thread, _stop_event
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_worker, daemon=True, name="FTSchedulerWorker")
    _scheduler_thread.start()

def stop_scheduler():
    global _stop_event
    _stop_event.set()

def toggle_scheduler(enabled: Optional[bool] = None) -> Dict[str, Any]:
    state = load_state()
    if enabled is None:
        state["enabled"] = not state.get("enabled", True)
    else:
        state["enabled"] = enabled
    
    if state["enabled"] and not state.get("next_run"):
        state["next_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    save_state(state)
    append_log(f"计划任务已{'开启' if state['enabled'] else '暂停'}")
    return state

def trigger_now(ignore_cooldown: bool = True) -> Dict[str, Any]:
    """Force run 1 scrape immediately (user manual trigger ignores circuit breaker cooldown)."""
    state = load_state()
    if ignore_cooldown and state.get("cooldown_until"):
        state["cooldown_until"] = None
        save_state(state)
    append_log("⚡ 用户手动触发单篇立即试跑 (忽略熔断休眠限制)...")
    res = execute_single_drip_scrape(ignore_cooldown=ignore_cooldown)
    return res



if __name__ == "__main__":
    print("Testing FT scheduler status...")
    st = load_state()
    print("State:", st)
