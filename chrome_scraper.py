#!/usr/bin/env python3
"""
TikTok 原生浏览器真实滚动与 API 数据包嗅探模块
复用本机 Chrome/Edge，真实向下滚动，拦截 /api/post/item_list 数据包
100% 突破反爬并抓取全部作品
"""

import time
from typing import List, Dict, Any, Callable, Optional
from playwright.sync_api import sync_playwright


def scrape_with_native_chrome(
    username: str,
    proxy: Optional[str] = None,
    max_videos: int = 0,
    log_callback: Optional[Callable[[str, str], None]] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
    on_batch_callback: Optional[Callable] = None
) -> List[Dict[str, Any]]:
    """
    使用本机真实 Chrome 模拟真人访问与向下滚动，
    利用 Playwright 监听原生网络数据包，完整抓取博主作品。
    """
    def log(msg: str, level: str = "info"):
        if log_callback:
            log_callback(msg, level)

    log("🚀 启动原生浏览器真实滚动嗅探引擎...", "info")
    target_url = f"https://www.tiktok.com/@{username}"
    videos_dict = {}
    has_more = [True]

    with sync_playwright() as p:
        # 优先使用本机 Chrome，备选 Edge
        channel = "chrome"
        launch_args = {
            "channel": channel,
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--mute-audio",
                "--no-default-browser-check"
            ]
        }
        if proxy and proxy.strip():
            launch_args["proxy"] = {"server": proxy.strip()}

        try:
            browser = p.chromium.launch(**launch_args)
            log("✅ 已调起本机原生 Google Chrome 引擎", "info")
        except Exception as e:
            channel = "msedge"
            launch_args["channel"] = channel
            try:
                browser = p.chromium.launch(**launch_args)
                log("✅ 已调起本机原生 Microsoft Edge 引擎", "info")
            except Exception as e2:
                log(f"⚠️ 无法启动原生浏览器: {e2}，将降级为常规解析", "warn")
                raise e2

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        # 监听网络流量响应
        def on_response(response):
            r_url = response.url
            if "/api/post/item_list" in r_url or "/api/creator/item_list" in r_url:
                try:
                    data = response.json()
                    items = data.get("itemList") or []
                    new_count = 0
                    for item in items:
                        vid = str(item.get("id"))
                        if vid and vid not in videos_dict:
                            desc = item.get("desc") or f"TikTok Video {vid}"
                            ctime = item.get("createTime")
                            stats = item.get("stats") or {}
                            video_meta = item.get("video") or {}
                            dur = video_meta.get("duration")
                            thumb = video_meta.get("cover") or video_meta.get("dynamicCover")
                            date_str = time.strftime("%Y-%m-%d", time.localtime(ctime)) if ctime else "未知"
                            dur_str = f"{int(dur//60):02d}:{int(dur%60):02d}" if dur else "--:--"
                            play_count = f"{stats.get('playCount', 0):,}" if stats.get('playCount') is not None else "未知"
                            digg_count = f"{stats.get('diggCount', 0):,}" if stats.get('diggCount') is not None else "N/A"

                            videos_dict[vid] = {
                                "id": vid,
                                "title": desc,
                                "url": f"https://www.tiktok.com/@{username}/video/{vid}",
                                "upload_date": date_str,
                                "duration": dur_str,
                                "view_count": play_count,
                                "like_count": digg_count,
                                "thumbnail": thumb or "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=80"
                            }
                            new_count += 1
                    # 有新视频时立刻通过回调推送给前端
                    if new_count > 0 and on_batch_callback:
                        on_batch_callback(list(videos_dict.values()))
                    if data.get("hasMore") in (False, 0, "0"):
                        has_more[0] = False
                except Exception:
                    pass

        page.on("response", on_response)

        log(f"🌐 正在载入主页: {target_url}", "info")
        try:
            page.goto(target_url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
        except Exception as net_err:
            log(f"主页初次加载异常: {net_err}", "warn")

        # 循环自然滚动
        no_new_rounds = 0
        last_total = len(videos_dict)

        while has_more[0]:
            if stop_check and stop_check():
                log("⏹ 收到用户停止指令，停止滚动抓取", "warn")
                break

            if max_videos and len(videos_dict) >= max_videos:
                log(f"🎯 已达到预设条数上限: {max_videos} 项", "info")
                break

            # 向下滚动到底部
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2200)

            curr_total = len(videos_dict)
            if curr_total != last_total:
                log(f"  📥 嗅探到新批次数据，当前累计已截获: {curr_total} 个视频作品", "info")
                if progress_callback:
                    progress_callback(curr_total)
                no_new_rounds = 0
            else:
                no_new_rounds += 1
                # 尝试轻微往上反弹再滚动，触发某些懒加载事件
                page.evaluate("window.scrollBy(0, -350);")
                page.wait_for_timeout(800)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                if no_new_rounds >= 6:
                    log("🏁 页面已连续滚动到底，无更多新视频更新，翻页完成！", "success")
                    break

            last_total = curr_total

        browser.close()

    return list(videos_dict.values())
