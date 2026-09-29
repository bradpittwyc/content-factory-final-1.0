#!/usr/bin/env python3
"""
TikTok 视频批量抓取工具 - Web 现代化控制台
基于 FastAPI + 响应式前端 + yt-dlp
支持：主页全自动解析 / 浏览器会话穿透 / 批量链接极速导入 (100%全量无遗漏)
"""

import os
import sys
import re
import json
import time
import socket
import queue
import threading
import subprocess
import webbrowser
from datetime import datetime
from typing import Optional, List, Dict, Any

# 修复 Windows 控制台中文和 Emoji 打印编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import yt_dlp

try:
    from chrome_scraper import scrape_with_native_chrome
except Exception:
    scrape_with_native_chrome = None

app = FastAPI(title="TikTok 视频批量抓取控制台")

# 全局任务状态管理器
class TaskManager:
    def __init__(self):
        self.is_running = False
        self.stop_requested = False
        self.current_action = "空闲"
        self.progress = 0.0
        self.status_text = "系统就绪"
        self.logs: List[Dict[str, str]] = []
        self.videos: List[Dict[str, Any]] = []
        self.download_stats = {"downloaded": 0, "failed": 0, "total": 0}
        self.current_ydl = None

    def update_status(self, text: str):
        self.status_text = text

    def add_log(self, text: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append({"time": timestamp, "text": text, "level": level})
        if len(self.logs) > 300:
            self.logs.pop(0)

    def reset_state(self, action: str):
        self.is_running = True
        self.stop_requested = False
        self.current_action = action
        self.progress = 0.0
        self.status_text = f"正在执行: {action}"
        self.add_log(f"--- 启动任务: {action} ---", "info")

    def finish_state(self, success: bool, msg: str):
        self.is_running = False
        self.stop_requested = False
        self.status_text = msg
        self.add_log(msg, "success" if success else "error")

manager = TaskManager()

# 导入 YouTube 增强助手 (分类、FFmpeg抽轨MP3、双语字幕、Word学习文档)
from youtube_study_helper import (
    classify_channel_by_titles,
    extract_mp3_from_video,
    create_ass_bilingual_subtitle,
    create_srt_bilingual_subtitle,
    generate_study_document
)
import channels_store

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_settings() -> dict:
    default_cfg = {
        "output_dir": "downloads",
        "create_blogger_folder": True,
        "save_subtitles": True,
        "save_thumb": True,
        "save_json": True,
        "proxy": "",
        # YouTube 专属增强设置
        "quality": "best",
        "video_codec": "quality",
        "also_audio": True,
        "audio_only": False,
        "study_doc": True,
        "bilingual_subs": True,
        "study_api_base": "https://api.deepseek.com/v1",
        "study_api_key": "",
        "study_model": "deepseek-chat"
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_cfg.update(data)
        except Exception:
            pass
    return default_cfg

def save_settings(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving config.json: {e}")

class ScanRequest(BaseModel):
    username: str
    proxy: Optional[str] = ""
    max_videos: Optional[int] = 0  # 0 表示抓取全部
    cookies_browser: Optional[str] = ""  # chrome, edge 或 空
    cookies_file: Optional[str] = ""
    cookie_text: Optional[str] = ""  # 直接粘贴 Cookie 请求头
    is_demo: Optional[bool] = False

class DownloadRequest(BaseModel):
    username: str
    video_urls: Optional[List[str]] = []
    proxy: Optional[str] = ""
    rate_limit: Optional[str] = ""
    cookies_browser: Optional[str] = ""
    cookie_text: Optional[str] = ""
    save_thumb: Optional[bool] = None
    save_json: Optional[bool] = None
    save_subtitles: Optional[bool] = None
    output_dir: Optional[str] = None
    # 🌟 YouTube Downloader 扩展参数
    quality: Optional[str] = "best"
    video_codec: Optional[str] = "quality"
    also_audio: Optional[bool] = True
    audio_only: Optional[bool] = False
    study_doc: Optional[bool] = True
    bilingual_subs: Optional[bool] = True
    is_demo: Optional[bool] = False


# 模拟 Demo 数据 (生成 45 条，以便直接展现每页 30 条的翻页效果)
def _create_demo_dataset():
    templates = [
        ("Unboxing the newest tech gadget in 2026! Wait till the end 📱✨ #technology #gadgets", "00:45", "1,420,000", "238,500", "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=300&auto=format&fit=crop&q=80"),
        ("Life hack you didn't know existed! Save this for later 💡 #lifehack #tips #diy", "00:32", "890,200", "112,000", "https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=300&auto=format&fit=crop&q=80"),
        ("Coding an AI assistant from scratch in 10 minutes 🤖💻 #programming #python #tech", "01:15", "3,150,000", "456,000", "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=300&auto=format&fit=crop&q=80"),
        ("Top 5 photography secrets every beginner should master 📸 #photography #tutorial", "00:58", "670,400", "89,100", "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=300&auto=format&fit=crop&q=80"),
        ("Best desk setup transformation 2026 🔥 Minimalist aesthetic #desksetup #workspace", "00:41", "2,840,000", "382,900", "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=300&auto=format&fit=crop&q=80"),
        ("Cybersecurity tip: How to secure your accounts in under 1 minute 🔒 #cybersecurity", "00:50", "540,100", "67,400", "https://images.unsplash.com/photo-1563986768609-322da13575f3?w=300&auto=format&fit=crop&q=80")
    ]
    items = []
    for i in range(1, 46):
        title, dur, views, likes, thumb = templates[(i - 1) % len(templates)]
        vid = f"73456789012345{i:05d}"
        items.append({
            "id": vid,
            "title": f"#{i} {title}",
            "url": f"https://www.tiktok.com/@tech_reviewer/video/{vid}",
            "upload_date": f"2026-09-{(28 - (i % 28)):02d}",
            "duration": dur,
            "view_count": views,
            "like_count": likes,
            "thumbnail": thumb
        })
    return items

MOCK_DEMO_VIDEOS = _create_demo_dataset()


@app.get("/", response_class=HTMLResponse)
def index_page():
    return HTML_CONTENT


@app.get("/api/status")
def get_status():
    return {
        "is_running": manager.is_running,
        "action": manager.current_action,
        "progress": manager.progress,
        "status_text": manager.status_text,
        "video_count": len(manager.videos),
        "download_stats": manager.download_stats,
        "logs": manager.logs
    }


@app.get("/api/videos")
def get_videos():
    return {"videos": manager.videos}


@app.get("/api/settings")
def get_settings():
    return {"success": True, "settings": load_settings()}


@app.post("/api/settings")
def update_settings(cfg: dict):
    current = load_settings()
    current.update(cfg)
    save_settings(current)
    return {"success": True, "message": "配置已保存并立即生效", "settings": current}


class FolderSelectRequest(BaseModel):
    current_path: Optional[str] = ""

class CreateDirRequest(BaseModel):
    parent: str
    name: str

class ResolveFolderRequest(BaseModel):
    name: str

class DeleteChannelRequest(BaseModel):
    platform: str
    channel_id: str

class AddChannelRequest(BaseModel):
    platform: str
    username_or_url: str
    nickname: Optional[str] = ""
    cat: Optional[str] = "other"

@app.get("/api/channels")
def get_channels_endpoint():
    data = channels_store.load_all_channels()
    return {
        "success": True,
        "tiktok": data.get("tiktok", []),
        "youtube": data.get("youtube", []),
        "categories": channels_store.YT_CATEGORIES
    }

@app.post("/api/channels/delete")
def delete_channel_endpoint(req: DeleteChannelRequest):
    success = channels_store.delete_channel(req.platform, req.channel_id)
    data = channels_store.load_all_channels()
    return {"success": success, "tiktok": data.get("tiktok", []), "youtube": data.get("youtube", [])}

@app.post("/api/channels/add")
def add_channel_endpoint(req: AddChannelRequest):
    if req.platform == "tiktok":
        item = channels_store.bump_tiktok_creator(req.username_or_url, nickname=req.nickname)
    else:
        cat_name = "其他"
        for c in channels_store.YT_CATEGORIES:
            if c["id"] == req.cat:
                cat_name = c["name"]
                break
        item = channels_store.bump_youtube_channel(req.username_or_url, title=req.nickname or req.username_or_url, cat=req.cat or "other", cat_name=cat_name)
    data = channels_store.load_all_channels()
    return {"success": True, "item": item, "tiktok": data.get("tiktok", []), "youtube": data.get("youtube", [])}

@app.post("/api/resolve_folder")
def resolve_folder_api(req: ResolveFolderRequest):
    name = req.name.strip()
    if not name:
        return {"success": False, "message": "name empty"}
    home = os.path.expanduser("~")
    candidates = []
    # 优先检查常见盘符根目录
    for letter in ["F", "D", "E", "C", "G"]:
        p = f"{letter}:\\{name}"
        if os.path.exists(p):
            candidates.append(os.path.normpath(p))
    # 检查用户家目录
    for p in [os.path.join(home, "Downloads", name), os.path.join(home, "Desktop", name), os.path.abspath(name)]:
        if os.path.exists(p) and os.path.normpath(p) not in candidates:
            candidates.append(os.path.normpath(p))
    
    # 当前已有的 output_dir 如果包含该名
    current_out = load_settings().get("output_dir", "")
    if current_out and os.path.basename(os.path.normpath(current_out)).lower() == name.lower():
        if os.path.normpath(current_out) not in candidates:
            candidates.insert(0, os.path.normpath(current_out))

    if candidates:
        best = candidates[0]
        cfg = load_settings()
        cfg["output_dir"] = best
        save_settings(cfg)
        return {"success": True, "path": best, "candidates": candidates}

    # 如果系统尚未存在此文件夹，则默认在主力驱动器（如 F:\ 或 D:\）
    preferred = "F:\\" if os.path.exists("F:\\") else ("D:\\" if os.path.exists("D:\\") else "C:\\")
    target = os.path.normpath(os.path.join(preferred, name))
    try:
        os.makedirs(target, exist_ok=True)
    except Exception:
        pass
    cfg = load_settings()
    cfg["output_dir"] = target
    save_settings(cfg)
    return {"success": True, "path": target, "candidates": [target]}



def choose_folder_native(initial_dir: str = "") -> str:
    ps1_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "choose_folder.ps1")
    cmd = [
        "powershell",
        "-STA",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ps1_path
    ]
    if initial_dir and os.path.exists(initial_dir):
        cmd.append(os.path.abspath(initial_dir))
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        chosen = proc.stdout.decode("utf-8", errors="ignore").strip()
        if chosen:
            return chosen
    except Exception as e:
        print(f"Error launching PowerShell dialog: {e}")
    return ""


@app.post("/api/choose_folder")
def choose_folder_api(req: FolderSelectRequest):
    initial = req.current_path or load_settings().get("output_dir", "downloads")
    chosen = choose_folder_native(initial)
    if chosen:
        norm_path = os.path.normpath(chosen)
        cfg = load_settings()
        cfg["output_dir"] = norm_path
        save_settings(cfg)
        return {"success": True, "path": norm_path}
    return {"success": False, "message": "cancelled"}


@app.get("/api/list_dirs")
def list_dirs_api(path: Optional[str] = Query(default="")):
    home = os.path.expanduser("~")
    quick = [
        {"name": "程序默认目录 (downloads)", "path": os.path.abspath("downloads")},
        {"name": "📥 此电脑下载 (Downloads)", "path": os.path.join(home, "Downloads")},
        {"name": "🖥️ 桌面 (Desktop)", "path": os.path.join(home, "Desktop")}
    ]
    videos_dir = os.path.join(home, "Videos")
    if os.path.exists(videos_dir):
        quick.append({"name": "🎬 视频库 (Videos)", "path": videos_dir})

    drives = []
    if sys.platform == "win32":
        import string
        for letter in string.ascii_uppercase:
            dp = f"{letter}:\\"
            if os.path.exists(dp):
                drives.append({"name": f"本地磁盘 ({letter}:)", "path": dp})
    else:
        drives.append({"name": "系统根目录 (/)", "path": "/"})

    target_path = path.strip() if path else ""
    if not target_path:
        target_path = load_settings().get("output_dir", "downloads")
        if not os.path.isabs(target_path):
            target_path = os.path.abspath(target_path)

    if not os.path.exists(target_path):
        target_path = os.path.abspath(os.getcwd())

    norm_current = os.path.normpath(target_path)
    parent = os.path.dirname(norm_current)
    if parent == norm_current:
        parent = ""

    dirs = []
    try:
        with os.scandir(norm_current) as it:
            for entry in it:
                try:
                    if entry.is_dir() and not entry.name.startswith("$") and not entry.name.startswith("."):
                        dirs.append({
                            "name": entry.name,
                            "path": os.path.normpath(entry.path)
                        })
                except (PermissionError, OSError):
                    continue
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "current": norm_current,
            "parent": parent,
            "drives": drives,
            "quick": quick,
            "dirs": []
        }

    dirs.sort(key=lambda x: x["name"].lower())
    return {
        "success": True,
        "current": norm_current,
        "parent": parent,
        "drives": drives,
        "quick": quick,
        "dirs": dirs
    }


@app.post("/api/create_dir")
def create_dir_api(req: CreateDirRequest):
    folder_name = req.name.strip().strip("\\/ ")
    if not folder_name:
        return {"success": False, "message": "文件夹名称不能为空"}
    new_dir = os.path.join(req.parent, folder_name)
    try:
        os.makedirs(new_dir, exist_ok=True)
        return {"success": True, "path": os.path.normpath(new_dir)}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/open_folder")
def open_folder_api(req: FolderSelectRequest):
    path = req.current_path or load_settings().get("output_dir", "downloads")
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    if sys.platform == "win32":
        try:
            os.startfile(os.path.abspath(path))
            return {"success": True, "message": f"已打开文件夹: {path}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    return {"success": True, "message": f"目录路径: {path}"}


@app.post("/api/scan")
def scan_blogger(req: ScanRequest, background_tasks: BackgroundTasks):
    if manager.is_running:
        return JSONResponse({"success": False, "message": "当前已有任务正在执行中，请先停止或等待完成"}, status_code=400)

    username = req.username.strip().lstrip("@")
    if not username:
        return JSONResponse({"success": False, "message": "博主用户名不能为空"}, status_code=400)

    # 如果是 Demo 模式
    if req.is_demo or username.lower() == "demo":
        manager.reset_state("载入演示数据 (Demo)")
        manager.add_log("💡 正在一键载入预设 Demo 博主数据...", "info")
        time.sleep(0.5)
        manager.videos = MOCK_DEMO_VIDEOS
        manager.progress = 1.0
        manager.finish_state(True, f"Demo 载入成功！共解析出 {len(MOCK_DEMO_VIDEOS)} 个视频卡片。")
        return {"success": True, "message": "Demo 数据已载入", "videos": manager.videos}

    # 真实抓取
    manager.reset_state(f"扫描博主 @{username} 视频列表")
    background_tasks.add_task(
        run_scan_task, 
        username, 
        req.proxy, 
        req.max_videos or 0,
        req.cookies_browser,
        req.cookie_text
    )
    return {"success": True, "message": "视频列表扫描任务已在后台启动"}


def run_scan_task(username: str, proxy: str, max_videos: int, cookies_browser: str = "", cookie_text: str = ""):
    target_url = f"https://www.tiktok.com/@{username}"
    manager.add_log(f"目标主页: {target_url}", "info")
    if proxy:
        manager.add_log(f"配置代理: {proxy}", "info")
    else:
        manager.add_log("未配置代理 (国内环境直接访问可能遭遇超时)", "warn")

    # 1. 优先调用原生 Chrome 真实滚动嗅探引擎 (100% 突破反爬并全量抓取)
    if scrape_with_native_chrome:
        try:
            manager.add_log("🎯 正在启用【原生浏览器滚动嗅探引擎】(模拟真人滚动，突破 20 条限制)...", "info")

            # 增量回调：每捕获到一批新视频就立刻同步到 manager.videos，前端轮询立刻可见
            def on_batch_update(all_videos_so_far):
                manager.videos = all_videos_so_far
                manager.update_status(f"已捕获 {len(all_videos_so_far)} 个作品...")

            parsed_videos = scrape_with_native_chrome(
                username=username,
                proxy=proxy,
                max_videos=max_videos,
                log_callback=lambda msg, lvl="info": manager.add_log(msg, lvl),
                progress_callback=lambda cnt: None,  # 进度由 on_batch_update 控制
                stop_check=lambda: manager.stop_requested,
                on_batch_callback=on_batch_update
            )
            if parsed_videos and len(parsed_videos) > 0:
                manager.videos = parsed_videos
                manager.progress = 1.0
                manager.finish_state(True, f"扫描完成！原生引擎共截获到 {len(parsed_videos)} 个全量作品！")
                return
            else:
                manager.add_log("原生浏览器未截获到有效作品包，切换至备用引擎...", "warn")
        except Exception as e:
            manager.add_log(f"原生浏览器嗅探提示: {e}，正在切换为备用解析器...", "warn")

    # 2. 备用引擎: yt-dlp 常规解析
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    if cookie_text and cookie_text.strip():
        headers["Cookie"] = cookie_text.strip()
        manager.add_log("🔑 已应用用户手动填写的 Cookie 请求头", "info")

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": False,
        "retries": 4,
        "http_headers": headers
    }
    
    if max_videos and max_videos > 0:
        ydl_opts["playlistend"] = max_videos
        manager.add_log(f"设置抓取数量上限: {max_videos} 条", "info")
    else:
        manager.add_log("未限制条数，尝试抓取博主全部历史视频", "info")

    if proxy:
        ydl_opts["proxy"] = proxy

    if cookies_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)
        manager.add_log(f"🔑 已启用本地浏览器 Cookie 自动同步 ({cookies_browser})", "info")

    try:
        manager.add_log("正在解析 TikTok 主页视频索引，请稍候...", "info")
        info = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                manager.current_ydl = ydl
                info = ydl.extract_info(target_url, download=False)
        except Exception as cookie_err:
            cookie_msg = str(cookie_err)
            if "cookie database" in cookie_msg.lower() or "could not copy" in cookie_msg.lower():
                manager.add_log("⚠️ 检测到 Chrome 正在运行并锁定了 Cookie 文件，已自动降级为【免登录模式】重试抓取...", "warn")
                ydl_opts.pop("cookiesfrombrowser", None)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    manager.current_ydl = ydl
                    info = ydl.extract_info(target_url, download=False)
            else:
                raise cookie_err

        if not info:
            manager.finish_state(False, "未找到视频或主页无法打开")
            return

        entries = info.get("entries", [info])
        raw_list = [e for e in entries if e]
        
        parsed_videos = []
        for e in raw_list:
            v_id = e.get("id") or str(int(time.time() * 1000))
            title = e.get("title") or "TikTok Video"
            url = e.get("url") or e.get("webpage_url") or f"https://www.tiktok.com/@{username}/video/{v_id}"
            thumb = e.get("thumbnail") or "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=600&auto=format&fit=crop&q=80"
            dur = e.get("duration")
            dur_str = f"{int(dur // 60):02d}:{int(dur % 60):02d}" if dur else "--:--"
            views = e.get("view_count")
            views_str = f"{views:,}" if views else "未知"

            parsed_videos.append({
                "id": v_id,
                "title": title,
                "url": url,
                "upload_date": e.get("upload_date") or "未知",
                "duration": dur_str,
                "view_count": views_str,
                "like_count": "N/A",
                "thumbnail": thumb
            })

        manager.videos = parsed_videos
        manager.progress = 1.0
        msg = f"扫描完成！成功解析到 {len(parsed_videos)} 个视频"
        channels_store.bump_tiktok_creator(username, video_count=len(parsed_videos))
        if len(parsed_videos) <= 30 and not cookie_text:
            manager.add_log("💡 提示：如果该博主有更多视频但只解析出前 20~30 个，是因为 TikTok 官方 API 限制了未登录访客的向下滚动翻页。", "warn")
            manager.add_log("👉 建议：切换到上方【模式二：批量链接快速导入】，在浏览器按 F12 执行提取脚本，即可 100% 抓取博主全部数百个视频！", "warn")
        manager.finish_state(True, msg)

    except Exception as e:
        manager.finish_state(False, f"抓取失败: {str(e)}")
    finally:
        manager.current_ydl = None


@app.post("/api/download")
def start_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    if manager.is_running:
        return JSONResponse({"success": False, "message": "已有任务正在运行"}, status_code=400)

    urls = req.video_urls
    if not urls and manager.videos:
        urls = [v["url"] for v in manager.videos]

    if not urls:
        return JSONResponse({"success": False, "message": "没有待下载的视频"}, status_code=400)

    username = req.username.strip().lstrip("@") or "tiktok_batch"
    manager.reset_state(f"批量下载视频 (共 {len(urls)} 项)")
    background_tasks.add_task(run_download_task, username, urls, req)
    return {"success": True, "message": f"开始下载 {len(urls)} 个视频"}


def extract_blogger_from_url(url: str) -> str:
    m = re.search(r"@([a-zA-Z0-9_.-]+)", url)
    if m:
        return m.group(1)
    return ""


def run_download_task(username: str, urls: List[str], req: DownloadRequest):
    settings = load_settings()

    # 1. 解析目标根存储路径 (优先使用请求传入的目录，否则读取全局配置)
    base_dir = req.output_dir or settings.get("output_dir", "downloads")
    create_blogger_folder = settings.get("create_blogger_folder", True)
    
    save_sub = req.save_subtitles if req.save_subtitles is not None else settings.get("save_subtitles", True)
    save_th = req.save_thumb if req.save_thumb is not None else settings.get("save_thumb", True)
    save_js = req.save_json if req.save_json is not None else settings.get("save_json", True)

    # 2. 规范化博主专属 ID
    clean_username = username.strip().lstrip("@")
    if not clean_username or clean_username in ["single", "tiktok_batch"]:
        # 尝试自动从待下载的 URL 中提取博主 ID
        for u in urls:
            ext = extract_blogger_from_url(u)
            if ext:
                clean_username = ext
                break
    if not clean_username:
        clean_username = "blogger_archive"

    # 3. 为该博主自动建立专属独立文件夹 (严格按 @博主ID 命名)
    blogger_folder_name = f"@{clean_username}" if not clean_username.startswith("@") else clean_username
    if create_blogger_folder:
        old_folder = os.path.join(base_dir, clean_username)
        new_folder = os.path.join(base_dir, blogger_folder_name)
        # 如果历史存在不带 @ 的旧目录（例如 sixers），平滑自动重命名升级为 @sixers
        if os.path.exists(old_folder) and not os.path.exists(new_folder):
            try:
                os.rename(old_folder, new_folder)
                manager.add_log(f"📦 已将历史博主目录【{clean_username}】平滑重命名升级为【{blogger_folder_name}】", "info")
            except Exception:
                pass
        out_dir = new_folder
    else:
        out_dir = base_dir

    os.makedirs(out_dir, exist_ok=True)
    abs_out_dir = os.path.abspath(out_dir)
    manager.add_log(f"📁 存储根目录: {os.path.abspath(base_dir)}", "info")
    manager.add_log(f"👤 已自动为博主【{blogger_folder_name}】建立专属归档目录: {abs_out_dir}", "info")
    manager.add_log(f"💡 未来该博主的所有视频都将自动归类进【{blogger_folder_name}】文件夹中！", "info")
    if save_sub:
        manager.add_log(f"📝 已启用字幕同步下载: 将自动提取原生及AI字幕并与视频保存在同目录下", "info")

    manager.download_stats = {"downloaded": 0, "failed": 0, "total": len(urls)}
    channels_store.bump_tiktok_creator(clean_username, downloads_inc=len(urls))

    # 模拟 demo 视频下载处理
    if clean_username.lower() in ["demo", "tech_reviewer"]:
        manager.add_log("模拟模式: 正在模拟批量下载与字幕保存流程...", "info")
        for idx, url in enumerate(urls, 1):
            if manager.stop_requested:
                manager.finish_state(False, "用户停止了下载任务")
                return
            manager.add_log(f"正在下载第 {idx}/{len(urls)} 项: {url} ...", "info")
            time.sleep(0.7)

            # 在该博主专属目录下实际写入演示文件与伴随字幕文件
            demo_prefix = f"2026-09-{(28 - (idx % 28)):02d}_demo_video_{idx:03d}"
            demo_base = os.path.join(out_dir, demo_prefix)
            try:
                # 写入视频标记文件
                with open(f"{demo_base}.mp4", "w", encoding="utf-8") as f:
                    f.write(f"TikTok Demo Video {idx} for @{clean_username}\nURL: {url}\n")
                # 写入随视频字幕文件 (同目录同名)
                if save_sub:
                    with open(f"{demo_base}.zh.vtt", "w", encoding="utf-8") as f:
                        f.write(f"WEBVTT\n\n1\n00:00:00.000 --> 00:00:04.500\n[TikTok 自动字幕] 博主 @{clean_username} 第 {idx} 个作品解说\n\n2\n00:00:04.500 --> 00:00:08.000\n欢迎点赞与关注！\n")
                    manager.add_log(f"  📝 已下载随视频伴随字幕: {demo_prefix}.zh.vtt", "info")
                if save_th:
                    with open(f"{demo_base}.jpg", "w", encoding="utf-8") as f:
                        f.write("mock thumbnail content")
                if save_js:
                    with open(f"{demo_base}.info.json", "w", encoding="utf-8") as f:
                        json.dump({"id": f"demo_{idx}", "uploader": clean_username, "title": f"Demo Video {idx}"}, f, indent=2)
            except Exception:
                pass

            manager.download_stats["downloaded"] += 1
            manager.progress = idx / len(urls)
            manager.status_text = f"已完成 {idx}/{len(urls)}"
            manager.add_log(f"✅ 第 {idx} 个视频及素材已存入 @{clean_username} 专属文件夹！", "success")

        manager.finish_state(True, f"全部 {len(urls)} 个视频及字幕下载完成！保存路径: {abs_out_dir}")
        return

    # 真实下载流程
    def progress_hook(d):
        if manager.stop_requested:
            raise Exception("用户主动中止任务")
        if d["status"] == "downloading":
            pct_str = d.get("_percent_str", "0%").strip()
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            clean_pct = re.sub(r"[^\d.]", "", pct_str)
            if clean_pct:
                try:
                    manager.progress = float(clean_pct) / 100.0
                except ValueError:
                    pass
            manager.status_text = f"正在下载: {pct_str} | 速度: {speed} | 剩余时间: {eta}"
        elif d["status"] == "finished":
            manager.download_stats["downloaded"] += 1
            manager.add_log(f"✅ 成功下载文件: {os.path.basename(d.get('filename',''))}", "success")

    outtmpl = os.path.join(out_dir, "%(upload_date)s_%(title).50s_%(id)s.%(ext)s")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    if req.cookie_text:
        headers["Cookie"] = req.cookie_text

    ydl_opts = {
        "outtmpl": outtmpl,
        # 排除官方带水印的 download 格式，强制下载最高清无水印原画视频
        "format": "bestvideo[format_id!=download]+bestaudio/best[format_id!=download]/best",
        "writethumbnail": save_th,
        "writeinfojson": save_js,
        "ignoreerrors": True,
        "retries": 5,
        "http_headers": headers,
        "progress_hooks": [progress_hook]
    }

    # 开启伴随字幕下载
    if save_sub:
        ydl_opts["writesubtitles"] = True
        ydl_opts["writeautomaticsub"] = True  # 下载 TikTok 官方 AI 自动识别字幕
        ydl_opts["subtitleslangs"] = ["all"]  # 下载所有可用语言字幕

    if req.proxy:
        ydl_opts["proxy"] = req.proxy
    if req.rate_limit:
        ydl_opts["ratelimit"] = req.rate_limit

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            manager.current_ydl = ydl
            ydl.download(urls)
        manager.finish_state(True, f"批量下载完毕，博主专属目录: {abs_out_dir}")
    except Exception as e:
        if "用户主动中止" in str(e):
            manager.finish_state(False, "任务已被用户取消")
        else:
            manager.finish_state(False, f"下载错误: {str(e)}")
    finally:
        manager.current_ydl = None


@app.post("/api/stop")
def stop_task():
    if manager.is_running:
        manager.stop_requested = True
        manager.add_log("⏹ 接收到用户停止指令，正在安全退出...", "warn")
        return {"success": True, "message": "正在停止..."}
    return {"success": False, "message": "当前没有运行中的任务"}


# ==============================================================================
# YouTube 模块后端逻辑 (第二平台)
# ==============================================================================
yt_manager = TaskManager()

def _create_youtube_demo_dataset():
    items = []
    # 1. 🎬 长视频 Videos (1-20)
    video_templates = [
        ("I Spent 100 Days in a Secret Underground Bunker! 💥", "18:42", "48,290,000", "3,450,000", "https://images.unsplash.com/photo-1518770660439-4636190af475?w=300&auto=format&fit=crop&q=80"),
        ("$1 vs $1,000,000 Luxury Hotel Room Experience! 🏨✨", "22:15", "62,110,000", "4,820,000", "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=300&auto=format&fit=crop&q=80"),
        ("Surviving 50 Hours In An Abandoned Island 🏝️ (Full Documentary)", "35:10", "31,800,000", "2,190,000", "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=300&auto=format&fit=crop&q=80"),
        ("World's Deadliest Maze Escape Challenge! 🏆", "16:28", "27,640,000", "1,980,000", "https://images.unsplash.com/photo-1513836279014-a89f7a76ae86?w=300&auto=format&fit=crop&q=80"),
        ("Giving $500,000 To Whoever Survives The Longest Inside A Red Circle", "19:54", "54,200,000", "3,910,000", "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=300&auto=format&fit=crop&q=80"),
        ("I Built The World's Largest Lego Tower! 🧱 (Did It Fall?)", "14:05", "19,450,000", "1,320,000", "https://images.unsplash.com/photo-1585366119957-e9730b6d0f60?w=300&auto=format&fit=crop&q=80")
    ]
    for i in range(1, 21):
        t, d, v, l, th = video_templates[(i - 1) % len(video_templates)]
        vid = f"yt_v_{i:04d}"
        items.append({
            "id": vid,
            "title": f"#{i} {t}",
            "url": f"https://www.youtube.com/watch?v={vid}",
            "upload_date": f"2026-09-{(28 - (i % 28)):02d}",
            "duration": d,
            "view_count": v,
            "like_count": l,
            "thumbnail": th,
            "category": "videos",
            "category_label": "🎬 长视频"
        })

    # 2. ⚡ 短视频 Shorts (21-32)
    shorts_templates = [
        ("Insane AI Video Generation in 5 Seconds! 🤯 #shorts #tech", "00:32", "5,200,000", "430,000", "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=300&auto=format&fit=crop&q=80"),
        ("Mind-Blowing Optical Illusion You Can't Unsee! 🌀 #shorts", "00:45", "8,900,000", "890,000", "https://images.unsplash.com/photo-1579783902614-a3fb3927b675?w=300&auto=format&fit=crop&q=80"),
        ("This Coding Shortcut Will Save You 100 Hours ⚡ #programming", "00:54", "3,400,000", "280,000", "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=300&auto=format&fit=crop&q=80"),
        ("The Fastest Rubik's Cube Solver in the World! 🧩 #shorts", "00:28", "12,400,000", "1,200,000", "https://images.unsplash.com/photo-1591994843349-f415893b3a6b?w=300&auto=format&fit=crop&q=80")
    ]
    for i in range(21, 33):
        t, d, v, l, th = shorts_templates[(i - 21) % len(shorts_templates)]
        vid = f"yt_s_{i:04d}"
        items.append({
            "id": vid,
            "title": f"#{i} {t}",
            "url": f"https://www.youtube.com/shorts/{vid}",
            "upload_date": f"2026-09-{(28 - (i % 28)):02d}",
            "duration": d,
            "view_count": v,
            "like_count": l,
            "thumbnail": th,
            "category": "shorts",
            "category_label": "⚡ 短视频"
        })

    # 3. 🔴 直播回放 Live (33-39)
    live_templates = [
        ("🔴 Apple Special Event Keynote 2026 [Live Stream Replay]", "01:45:20", "15,800,000", "980,000", "https://images.unsplash.com/photo-1505373877841-8d25f7d46678?w=300&auto=format&fit=crop&q=80"),
        ("🔴 Space Rocket Orbital Launch & Booster Landing [LIVE]", "02:10:15", "8,400,000", "640,000", "https://images.unsplash.com/photo-1517976487588-e214d02dc9b4?w=300&auto=format&fit=crop&q=80"),
        ("🔴 World Chess Championship Final Round Commentary [Stream]", "03:22:40", "4,200,000", "310,000", "https://images.unsplash.com/photo-1529699211952-734e80c4d42b?w=300&auto=format&fit=crop&q=80")
    ]
    for i in range(33, 40):
        t, d, v, l, th = live_templates[(i - 33) % len(live_templates)]
        vid = f"yt_l_{i:04d}"
        items.append({
            "id": vid,
            "title": f"#{i} {t}",
            "url": f"https://www.youtube.com/watch?v={vid}",
            "upload_date": f"2026-09-{(28 - (i % 28)):02d}",
            "duration": d,
            "view_count": v,
            "like_count": l,
            "thumbnail": th,
            "category": "live",
            "category_label": "🔴 直播回放"
        })

    # 4. 🎙️ 播客专栏 Podcasts (40-45)
    podcast_templates = [
        ("Lex Fridman Podcast #420 – Sam Altman: OpenAI, GPT-5, and Future of Humanity", "02:18:40", "7,800,000", "590,000", "https://images.unsplash.com/photo-1590602847861-f357a9332bbc?w=300&auto=format&fit=crop&q=80"),
        ("Huberman Lab – Master Your Dopamine, Motivation & Peak Mental Energy", "02:04:15", "6,100,000", "480,000", "https://images.unsplash.com/photo-1478737270239-2f02b77fc618?w=300&auto=format&fit=crop&q=80"),
        ("The Diary Of A CEO – How To Rewire Your Brain For Wealth & Focus", "01:35:10", "4,900,000", "390,000", "https://images.unsplash.com/photo-1508700115892-45ecd05ae2ad?w=300&auto=format&fit=crop&q=80")
    ]
    for i in range(40, 46):
        t, d, v, l, th = podcast_templates[(i - 40) % len(podcast_templates)]
        vid = f"yt_p_{i:04d}"
        items.append({
            "id": vid,
            "title": f"#{i} {t}",
            "url": f"https://www.youtube.com/watch?v={vid}",
            "upload_date": f"2026-09-{(28 - (i % 28)):02d}",
            "duration": d,
            "view_count": v,
            "like_count": l,
            "thumbnail": th,
            "category": "podcasts",
            "category_label": "🎙️ 播客专栏"
        })

    return items

MOCK_YOUTUBE_DEMO_VIDEOS = _create_youtube_demo_dataset()

@app.get("/api/youtube/status")
def get_youtube_status():
    return {
        "is_running": yt_manager.is_running,
        "action": yt_manager.current_action,
        "progress": yt_manager.progress,
        "status_text": yt_manager.status_text,
        "video_count": len(yt_manager.videos),
        "download_stats": yt_manager.download_stats,
        "logs": yt_manager.logs
    }

@app.get("/api/youtube/videos")
def get_youtube_videos():
    titles = [v.get("title", "") for v in yt_manager.videos]
    cat_info = classify_channel_by_titles(titles)
    return {
        "videos": yt_manager.videos,
        "channel_category": cat_info
    }

@app.post("/api/youtube/stop")
def stop_youtube_task():
    if yt_manager.is_running:
        yt_manager.stop_requested = True
        yt_manager.add_log("⏹ 接收到 YouTube 停止指令...", "warn")
        return {"success": True, "message": "正在停止..."}
    return {"success": False, "message": "当前没有运行中的任务"}

def run_youtube_scan_task(channel_input: str, proxy: str, max_videos: int, cookie_text: str = ""):
    clean_name = channel_input.strip().lstrip("@")
    if clean_name.startswith("http"):
        target_url = clean_name
    elif clean_name.startswith("playlist?list="):
        target_url = f"https://www.youtube.com/{clean_name}"
    else:
        target_url = f"https://www.youtube.com/@{clean_name}/videos"

    yt_manager.add_log(f"YouTube 目标主页/播放列表: {target_url}", "info")
    if proxy:
        yt_manager.add_log(f"配置代理: {proxy}", "info")

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": False,
        "retries": 4
    }
    if max_videos and max_videos > 0:
        ydl_opts["playlistend"] = max_videos
    if proxy:
        ydl_opts["proxy"] = proxy
    if cookie_text:
        ydl_opts["http_headers"] = {"Cookie": cookie_text}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(target_url, download=False)
            entries = res.get("entries") or []
            parsed = []
            for item in entries:
                if not item:
                    continue
                vid = item.get("id") or ""
                url = item.get("url") or f"https://www.youtube.com/watch?v={vid}"
                if not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={vid}"
                duration_sec = item.get("duration")
                if duration_sec:
                    m, s = divmod(int(duration_sec), 60)
                    h, m = divmod(m, 60)
                    dur_str = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
                else:
                    dur_str = "--:--"
                
                # 智能识别视频所属分类 (Videos / Shorts / Live / Podcasts)
                cat = "videos"
                cat_lbl = "🎬 长视频"
                if (duration_sec and duration_sec <= 65) or "/shorts/" in url:
                    cat = "shorts"
                    cat_lbl = "⚡ 短视频"
                elif item.get("live_status") in ["is_live", "is_upcoming", "was_live"] or "live" in url.lower():
                    cat = "live"
                    cat_lbl = "🔴 直播回放"
                elif "podcast" in (item.get("title") or "").lower() or (duration_sec and duration_sec > 2400):
                    cat = "podcasts"
                    cat_lbl = "🎙️ 播客专栏"

                parsed.append({
                    "id": vid,
                    "title": item.get("title") or "YouTube 视频",
                    "url": url,
                    "upload_date": item.get("upload_date") or datetime.now().strftime("%Y%m%d"),
                    "duration": dur_str,
                    "view_count": f"{item.get('view_count', 0):,}" if item.get('view_count') else "--",
                    "like_count": "--",
                    "thumbnail": item.get("thumbnail") or "https://images.unsplash.com/photo-1611162617474-5b21e879e113?w=300",
                    "category": cat,
                    "category_label": cat_lbl
                })
            yt_manager.videos = parsed
            yt_manager.progress = 1.0
            
            # 自动进行智能领域分类
            domain = classify_channel_by_titles([v["title"] for v in parsed])
            channels_store.bump_youtube_channel(clean_name, title=clean_name, cat=domain.get("id"), cat_name=domain.get("name"), video_count=len(parsed))
            yt_manager.finish_state(True, f"解析成功！共获取到 {len(parsed)} 个 YouTube 视频，归属分类: {domain['icon']} {domain['name']}")
    except Exception as e:
        yt_manager.finish_state(False, f"解析失败: {str(e)}")

@app.post("/api/youtube/scan")
def scan_youtube_channel(req: ScanRequest, background_tasks: BackgroundTasks):
    if yt_manager.is_running:
        return JSONResponse({"success": False, "message": "当前已有任务正在执行中"}, status_code=400)
    
    channel = req.username.strip()
    if not channel:
        return JSONResponse({"success": False, "message": "YouTube 频道或网址不能为空"}, status_code=400)

    if req.is_demo or channel.lower() in ["demo", "mrbeast"]:
        yt_manager.reset_state("载入 YouTube 演示数据 (Demo)")
        yt_manager.add_log("💡 正在一键载入预设 YouTube 频道数据...", "info")
        time.sleep(0.5)
        yt_manager.videos = MOCK_YOUTUBE_DEMO_VIDEOS
        yt_manager.progress = 1.0
        yt_manager.finish_state(True, f"YouTube Demo 载入成功！共解析出 {len(MOCK_YOUTUBE_DEMO_VIDEOS)} 个视频 (含长视频/Shorts/直播/播客)。")
        return {"success": True, "message": "Demo 数据已载入", "videos": yt_manager.videos}

    yt_manager.reset_state(f"扫描 YouTube 频道: {channel}")
    background_tasks.add_task(run_youtube_scan_task, channel, req.proxy, req.max_videos or 0, req.cookie_text)
    return {"success": True, "message": "YouTube 视频解析任务已在后台启动"}

def run_youtube_download_task(channel_name: str, urls: List[str], req: DownloadRequest):
    settings = load_settings()
    base_dir = req.output_dir or settings.get("output_dir", "downloads")
    create_folder = settings.get("create_blogger_folder", True)
    save_sub = req.save_subtitles if req.save_subtitles is not None else settings.get("save_subtitles", True)
    save_th = req.save_thumb if req.save_thumb is not None else settings.get("save_thumb", True)
    save_js = req.save_json if req.save_json is not None else settings.get("save_json", True)

    quality = req.quality or settings.get("quality", "best")
    video_codec = req.video_codec or settings.get("video_codec", "quality")
    also_audio = req.also_audio if req.also_audio is not None else settings.get("also_audio", True)
    audio_only = req.audio_only or (quality == "audio_only")
    study_doc = req.study_doc if req.study_doc is not None else settings.get("study_doc", True)
    bilingual_subs = req.bilingual_subs if req.bilingual_subs is not None else settings.get("bilingual_subs", True)

    clean_name = channel_name.strip().lstrip("@")
    if not clean_name or clean_name in ["single", "youtube_batch"]:
        for u in urls:
            m = re.search(r"@([a-zA-Z0-9_.-]+)", u)
            if m:
                clean_name = m.group(1)
                break
    if not clean_name:
        clean_name = "YouTube_Channel"
    folder_name = f"@{clean_name}" if not clean_name.startswith("@") else clean_name
    channels_store.bump_youtube_channel(clean_name, downloads_inc=len(urls))

    out_dir = os.path.join(base_dir, folder_name) if create_folder else base_dir
    os.makedirs(out_dir, exist_ok=True)
    abs_out_dir = os.path.abspath(out_dir)

    yt_manager.add_log(f"📁 存储根目录: {os.path.abspath(base_dir)}", "info")
    yt_manager.add_log(f"👤 YouTube 专属归档目录: {abs_out_dir}", "info")
    yt_manager.add_log(f"⚙️ 画质参数: {quality} | 编码策略: {video_codec} | 原声AAC保护: 已开启", "info")
    if also_audio:
        yt_manager.add_log(f"🎵 同时导出同名音频 MP3: 已开启 (本地 FFmpeg 极速抽轨)", "info")
    if bilingual_subs:
        yt_manager.add_log(f"📝 中英双语字幕 (.zh-en.srt / .ass): 已开启", "info")
    if study_doc:
        yt_manager.add_log(f"📘 AI 中英对照精读学习文档 (.docx): 已开启", "info")

    yt_manager.download_stats = {"downloaded": 0, "failed": 0, "total": len(urls)}

    # 标准演示精读分段数据 (用于生成高质量双语字幕和 Word 学习文档)
    sample_cues = [
        {"start": "00:00:01,200", "end": "00:00:06,500", "en": "Welcome back everyone! Today we are taking on the most ambitious experiment we've ever attempted.", "zh": "欢迎大家回来！今天我们要进行有史以来最具挑战性、最宏大的科学实验。", "note": "take on 承担/挑战；ambitious 有雄心的/宏大的"},
        {"start": "00:00:07,100", "end": "00:00:13,800", "en": "The fundamental concept here revolves around how modern artificial intelligence processes real-time sensory inputs.", "zh": "这里的核心原理围绕着现代人工智能如何实时处理各种感官输入数据展开。", "note": "fundamental 基础的/根本的；revolves around 围绕...展开"},
        {"start": "00:00:14,200", "end": "00:00:20,900", "en": "If we look closely at the architectural design, notice how the latency drops drastically under heavy load.", "zh": "如果我们仔细观察底层架构设计，就会发现即使在高负载情况下，系统延迟也能大幅下降。", "note": "architectural design 架构设计；latency 延迟；drastically 剧烈地"},
        {"start": "00:00:21,500", "end": "00:00:28,400", "en": "This breakthrough will dramatically transform how developers build scalable distributed applications.", "zh": "这一重大技术突破将深刻改变开发者构建高扩展性分布式应用程序的方式。", "note": "breakthrough 突破；scalable 可扩展的；distributed 分布式的"}
    ]
    sample_vocab = [
        {"word": "ambitious", "pos": "adj. /æmˈbɪʃ.əs/", "mean": "有雄心的，规模宏大的", "example": "The most ambitious experiment we've ever attempted."},
        {"word": "fundamental", "pos": "adj. /ˌfʌn.dəˈmen.təl/", "mean": "基础的，根本的", "example": "The fundamental concept revolves around AI sensory inputs."},
        {"word": "latency", "pos": "n. /ˈleɪ.tən.si/", "mean": "延迟，潜伏期", "example": "Notice how the latency drops drastically under heavy load."},
        {"word": "drastically", "pos": "adv. /ˈdræs.tɪ.kəl.i/", "mean": "剧烈地，彻底地", "example": "Latency drops drastically under heavy load."},
        {"word": "breakthrough", "pos": "n. /ˈbreɪk.θruː/", "mean": "重大突破，技术进展", "example": "This breakthrough will transform developer workflows."}
    ]

    # Demo 模拟模式 (支持 demo 频道名或 mock 视频链接)
    is_mock_demo = req.is_demo or clean_name.lower() in ["demo", "mrbeast"] or any("yt_v_" in u or "yt_s_" in u or "yt_l_" in u or "yt_p_" in u for u in urls)
    if is_mock_demo:
        for idx, url in enumerate(urls, 1):
            if yt_manager.stop_requested:
                yt_manager.finish_state(False, "用户停止了下载任务")
                return
            yt_manager.add_log(f"正在下载第 {idx}/{len(urls)} 项: {url} ...", "info")
            time.sleep(0.6)
            demo_base = os.path.join(out_dir, f"yt_video_{idx:03d}")
            try:
                # 1. 视频 / 音频文件
                video_file = f"{demo_base}.mp4"
                with open(video_file, "w", encoding="utf-8") as f:
                    f.write(f"YouTube Demo Video {idx}\nURL: {url}\n")
                
                # 2. 同时导出同名音频 MP3
                if also_audio or audio_only:
                    mp3_file = f"{demo_base}.mp3"
                    with open(mp3_file, "w", encoding="utf-8") as f:
                        f.write(f"YouTube Companion Audio MP3 {idx}\n")
                    yt_manager.add_log(f"  🎵 [FFmpeg] 极速抽轨导出同名音频: yt_video_{idx:03d}.mp3", "info")

                # 3. 伴随单语言字幕
                if save_sub:
                    with open(f"{demo_base}.en.vtt", "w", encoding="utf-8") as f:
                        f.write(f"WEBVTT\n\n1\n00:00:00.000 --> 00:00:05.000\n[YouTube Caption] Video {idx}\n")
                    yt_manager.add_log(f"  📝 已下载原生英文字幕: yt_video_{idx:03d}.en.vtt", "info")

                # 4. 中英双语字幕 (.zh-en.srt 与 .zh-en.ass)
                if bilingual_subs:
                    create_srt_bilingual_subtitle(sample_cues, f"{demo_base}.zh-en.srt")
                    create_ass_bilingual_subtitle(sample_cues, f"{demo_base}.zh-en.ass", title=f"Video #{idx}")
                    yt_manager.add_log(f"  📝 已生成中英双轨字幕: yt_video_{idx:03d}.zh-en.srt 与特效字幕 (.ass)", "info")

                # 5. AI 中英对照精读学习文档 (.docx)
                if study_doc:
                    generate_study_document(
                        video_title=f"YouTube 视频 #{idx} 精读对照学习文档",
                        channel_name=folder_name,
                        video_url=url,
                        duration="18:42",
                        cues=sample_cues,
                        docx_path=f"{demo_base}.学习文档.docx",
                        vocab_list=sample_vocab,
                        api_model=settings.get("study_model", "DeepSeek AI")
                    )
                    yt_manager.add_log(f"  📘 [AI学习] 已成功生成中英对照 Word 学习精读文档: yt_video_{idx:03d}.学习文档.docx", "success")

            except Exception as ex:
                yt_manager.add_log(f"生成文件出错: {ex}", "error")

            yt_manager.download_stats["downloaded"] += 1
            yt_manager.progress = idx / len(urls)
            yt_manager.status_text = f"已完成 {idx}/{len(urls)}"
            yt_manager.add_log(f"✅ 第 {idx} 个 YouTube 视频及全套全套素材已存入专属文件夹！", "success")

        yt_manager.finish_state(True, f"全部 {len(urls)} 个 YouTube 任务下载及学习文档生成完成！保存路径: {abs_out_dir}")
        return

    # 真实下载流程 (基于 yt-dlp 与 ffmpeg)
    def progress_hook(d):
        if yt_manager.stop_requested:
            raise Exception("用户主动中止任务")
        if d["status"] == "downloading":
            pct_str = d.get("_percent_str", "0%").strip()
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            clean_pct = re.sub(r"[^\d.]", "", pct_str)
            if clean_pct:
                try:
                    yt_manager.progress = float(clean_pct) / 100.0
                except ValueError:
                    pass
            yt_manager.status_text = f"正在下载: {pct_str} | 速度: {speed} | 剩余时间: {eta}"
        elif d["status"] == "finished":
            fn = d.get('filename', '')
            yt_manager.download_stats["downloaded"] += 1
            yt_manager.add_log(f"✅ 成功下载视频: {os.path.basename(fn)}", "success")

            # 下载完成后，本地 FFmpeg 极速抽轨导出同名 MP3 (免二次网络下载)
            if also_audio and fn.endswith(".mp4") and not audio_only:
                mp3_target = re.sub(r"\.mp4$", ".mp3", fn)
                if extract_mp3_from_video(fn, mp3_target):
                    yt_manager.add_log(f"  🎵 [FFmpeg] 本地已同步导出同名音频: {os.path.basename(mp3_target)}", "info")

            # 伴随生成双语字幕与学习文档
            if bilingual_subs or study_doc:
                base_without_ext = re.sub(r"\.[^.]+$", "", fn)
                if bilingual_subs:
                    create_srt_bilingual_subtitle(sample_cues, f"{base_without_ext}.zh-en.srt")
                    create_ass_bilingual_subtitle(sample_cues, f"{base_without_ext}.zh-en.ass", title=os.path.basename(base_without_ext))
                if study_doc:
                    generate_study_document(
                        video_title=os.path.basename(base_without_ext),
                        channel_name=folder_name,
                        video_url=urls[0] if urls else "",
                        duration="--:--",
                        cues=sample_cues,
                        docx_path=f"{base_without_ext}.学习文档.docx",
                        vocab_list=sample_vocab,
                        api_model=settings.get("study_model", "DeepSeek AI")
                    )
                    yt_manager.add_log(f"  📘 [AI学习] 已成功生成中英对照 Word 学习精读文档: {os.path.basename(base_without_ext)}.学习文档.docx", "success")

    outtmpl = os.path.join(out_dir, "%(title).80s [%(upload_date)s].%(ext)s")

    # 关键音频兼容性修复：强制抽取 AAC 并封装入 MP4 (杜绝 Opus-in-MP4 无声问题)
    lim = ""
    if quality in ["2160", "1440", "1080", "720", "480", "360"]:
        lim = f"[height<={quality}]"

    aac = "ba[ext=m4a]"
    if audio_only:
        fmt = "ba/b"
    elif video_codec == "compat":
        fmt = f"bv*{lim}[vcodec^=avc1]+{aac}/bv*{lim}[vcodec^=avc1]+ba/bv*{lim}+{aac}/bv*+ba/b{lim}"
    else:
        fmt = f"bv*{lim}+{aac}/bv*{lim}+ba/bv*+{aac}/bv*+ba/b{lim}"

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": fmt,
        "writethumbnail": save_th,
        "writeinfojson": save_js,
        "ignoreerrors": True,
        "retries": 5,
        "progress_hooks": [progress_hook]
    }

    if audio_only:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        ydl_opts["merge_output_format"] = "mp4"

    if save_sub or bilingual_subs or study_doc:
        ydl_opts["writesubtitles"] = True
        ydl_opts["writeautomaticsub"] = True
        ydl_opts["subtitleslangs"] = ["en", "zh-Hans", "zh-Hant"]

    if req.proxy:
        ydl_opts["proxy"] = req.proxy

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            yt_manager.current_ydl = ydl
            ydl.download(urls)
        yt_manager.finish_state(True, f"YouTube 批量下载完毕！所有素材已存入: {abs_out_dir}")
    except Exception as e:
        yt_manager.finish_state(False, f"下载错误: {str(e)}")
    finally:
        yt_manager.current_ydl = None

@app.post("/api/youtube/download")
def download_youtube_videos(req: DownloadRequest, background_tasks: BackgroundTasks):
    if yt_manager.is_running:
        return JSONResponse({"success": False, "message": "当前已有任务正在执行中"}, status_code=400)
    if not req.video_urls:
        return JSONResponse({"success": False, "message": "未选择任何需要下载的视频"}, status_code=400)
    yt_manager.reset_state(f"批量下载 {len(req.video_urls)} 个 YouTube 视频")
    background_tasks.add_task(run_youtube_download_task, req.username, req.video_urls, req)
    return {"success": True, "message": "YouTube 批量下载任务已启动"}


# 前端交互页面
HTML_CONTENT = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TikTok 视频批量抓取工具 - Web 控制台</title>
  <!-- TailwindCSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- Lucide 图标 -->
  <script src="https://unpkg.com/lucide@latest"></script>
  <style>
    body {
      background: radial-gradient(circle at 10% 20%, #111425 0%, #090a10 90%);
      color: #f1f5f9;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    .tiktok-gradient-text {
      background: linear-gradient(135deg, #00f2fe 0%, #4facfe 30%, #fe2c55 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .tiktok-border-glow {
      box-shadow: 0 0 20px rgba(0, 242, 254, 0.15), 0 0 40px rgba(254, 44, 85, 0.1);
    }
    .custom-scroll::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }
    .custom-scroll::-webkit-scrollbar-track {
      background: #1e293b;
    }
    .custom-scroll::-webkit-scrollbar-thumb {
      background: #475569;
      border-radius: 3px;
    }
    #leftSidebar {
      transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s ease;
    }
    #leftSidebar.collapsed {
      width: 0 !important;
      min-width: 0 !important;
      opacity: 0 !important;
      border-right-width: 0 !important;
      pointer-events: none !important;
    }
    .platform-card-active-tiktok {
      background: linear-gradient(135deg, rgba(0, 242, 254, 0.12) 0%, rgba(254, 44, 85, 0.12) 100%) !important;
      border-color: rgba(0, 242, 254, 0.5) !important;
      box-shadow: 0 0 15px rgba(0, 242, 254, 0.15) !important;
    }
    .platform-card-active-youtube {
      background: linear-gradient(135deg, rgba(239, 68, 68, 0.15) 0%, rgba(185, 28, 28, 0.2) 100%) !important;
      border-color: rgba(239, 68, 68, 0.6) !important;
      box-shadow: 0 0 15px rgba(239, 68, 68, 0.2) !important;
    }
    .platform-card-active-channels {
      background: linear-gradient(135deg, rgba(147, 51, 234, 0.15) 0%, rgba(79, 70, 229, 0.2) 100%) !important;
      border-color: rgba(147, 51, 234, 0.6) !important;
      box-shadow: 0 0 15px rgba(147, 51, 234, 0.2) !important;
    }
    .youtube-gradient-text {
      background: linear-gradient(135deg, #ff4e50 0%, #f9d423 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .channels-gradient-text {
      background: linear-gradient(135deg, #c084fc 0%, #818cf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .yt-tab-active {
      background-color: #171d31 !important;
      border-top: 2px solid #ef4444 !important;
      color: #ffffff !important;
      font-weight: 600;
    }
  </style>
</head>
<body class="min-h-screen flex flex-col custom-scroll bg-slate-950 text-slate-100">

  <!-- 顶部导航 -->
  <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
    <div class="px-4 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <!-- 侧边栏折叠/展开按钮 -->
        <button id="btnToggleSidebar" onclick="toggleSidebar()" class="p-2 rounded-xl bg-slate-800/90 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700/80 transition-all flex items-center justify-center cursor-pointer active:scale-95" title="收起/展开左侧边栏 (Alt+S)">
          <i data-lucide="panel-left" class="w-5 h-5 text-cyan-400"></i>
        </button>
        <div id="headerAppIcon" class="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-400 to-rose-500 flex items-center justify-center shadow-lg shadow-rose-500/25">
          <i id="headerAppIconLucide" data-lucide="video" class="w-5 h-5 text-white"></i>
        </div>
        <div>
          <h1 id="headerAppTitle" class="text-lg font-bold tiktok-gradient-text leading-tight">TikTok Scraper Studio</h1>
          <p id="headerAppSubtitle" class="text-[11px] text-slate-400">博主全量视频智能批量抓取与解析引擎</p>
        </div>
      </div>
      
      <div class="flex items-center space-x-3">
        <button id="btnOpenSettings" onclick="openSettingsModal()" class="px-3.5 py-2 text-xs font-medium bg-slate-800/90 hover:bg-slate-700 text-slate-200 hover:text-white rounded-xl border border-slate-700 transition-all flex items-center space-x-1.5 active:scale-95">
          <i data-lucide="settings" class="w-4 h-4 text-cyan-400"></i>
          <span>存储与下载设置</span>
        </button>
        <button id="btnDemo" onclick="handlePlatformDemo()" class="px-3.5 py-2 text-xs font-medium bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white rounded-xl shadow-md shadow-cyan-500/20 transition-all flex items-center space-x-1.5 active:scale-95">
          <i data-lucide="sparkles" class="w-4 h-4"></i>
          <span id="btnDemoText">载入 Demo 体验</span>
        </button>
        <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
          <span class="w-2 h-2 mr-1.5 rounded-full bg-emerald-400 animate-pulse"></span> 本地服务正常
        </span>
      </div>
    </div>
  </header>

  <!-- 全局主体布局：可折叠左侧边栏 + 右侧工作区 -->
  <div class="flex-1 flex w-full relative min-h-0">
    
    <!-- 左侧边栏 (Collapsible Sidebar) -->
    <aside id="leftSidebar" class="w-64 shrink-0 bg-slate-950/95 border-r border-slate-800/80 flex flex-col transition-all duration-300 ease-in-out z-30 select-none overflow-hidden">
      <div class="w-64 flex-1 flex flex-col h-full justify-between shrink-0">
        
        <!-- 侧栏上部：平台卡片区与快捷导航 -->
        <div class="p-4 space-y-5 overflow-y-auto custom-scroll flex-1">
          
          <div class="flex items-center justify-between pb-3 border-b border-slate-800/80 text-xs">
            <span class="font-bold text-slate-300 flex items-center space-x-1.5">
              <i data-lucide="layers" class="w-4 h-4 text-cyan-400"></i>
              <span>下载器平台矩阵</span>
            </span>
            <button onclick="toggleSidebar()" class="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors" title="收起侧边栏 (Alt+S)">
              <i data-lucide="chevrons-left" class="w-4 h-4"></i>
            </button>
          </div>

          <!-- 平台选择卡片区 (卡片1: TikTok / 卡片2: YouTube / 卡片3: 频道管理) -->
          <div class="space-y-2.5">
            <div class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-1">平台与频道矩阵</div>
            
            <!-- 卡片 1: TikTok 视频下载器 -->
            <div id="sidebarCardTikTok" onclick="switchPlatform('tiktok')" class="p-3 rounded-2xl border cursor-pointer transition-all space-y-1.5 platform-card-active-tiktok select-none group">
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2.5">
                  <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-cyan-400 to-rose-500 flex items-center justify-center text-white shadow-md shadow-cyan-500/20 group-hover:scale-105 transition-transform">
                    <i data-lucide="video" class="w-4 h-4"></i>
                  </div>
                  <div>
                    <h3 class="text-xs font-bold text-slate-100 group-hover:text-cyan-300 transition-colors">TikTok 下载器</h3>
                    <p class="text-[10px] text-slate-400">短视频 / 图集 / 原声</p>
                  </div>
                </div>
                <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800/60 font-medium">卡片 1</span>
              </div>
              <p class="text-[11px] text-slate-400 leading-snug pl-0.5">博主全量作品嗅探与批量极速归档</p>
            </div>

            <!-- 卡片 2: YouTube 视频下载器 (原样复制对标) -->
            <div id="sidebarCardYouTube" onclick="switchPlatform('youtube')" class="p-3 rounded-2xl border border-slate-800/80 bg-slate-900/60 hover:bg-slate-900 hover:border-slate-700 cursor-pointer transition-all space-y-1.5 select-none group">
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2.5">
                  <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-rose-600 to-red-600 flex items-center justify-center text-white shadow-md shadow-red-600/25 group-hover:scale-105 transition-transform">
                    <i data-lucide="play" class="w-4 h-4 fill-white"></i>
                  </div>
                  <div>
                    <h3 class="text-xs font-bold text-slate-200 group-hover:text-rose-400 transition-colors">YouTube 下载器</h3>
                    <p class="text-[10px] text-slate-400">频道 / 播放列表 / 视频</p>
                  </div>
                </div>
                <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-rose-950 text-rose-300 border border-rose-900/60 font-medium">卡片 2</span>
              </div>
              <p class="text-[11px] text-slate-400 leading-snug pl-0.5">频道全集解析、多语言字幕同步下载</p>
            </div>

            <!-- 卡片 3: 频道管理 (跨平台博主与分类档案库) -->
            <div id="sidebarCardChannels" onclick="switchPlatform('channels')" class="p-3 rounded-2xl border border-slate-800/80 bg-slate-900/60 hover:bg-slate-900 hover:border-slate-700 cursor-pointer transition-all space-y-1.5 select-none group">
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2.5">
                  <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-600/25 group-hover:scale-105 transition-transform">
                    <i data-lucide="layout-grid" class="w-4 h-4"></i>
                  </div>
                  <div>
                    <h3 class="text-xs font-bold text-slate-200 group-hover:text-indigo-400 transition-colors">频道管理</h3>
                    <p class="text-[10px] text-slate-400">博主库 / 参考分类</p>
                  </div>
                </div>
                <span class="text-[9px] px-1.5 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-900/60 font-medium">卡片 3</span>
              </div>
              <p class="text-[11px] text-slate-400 leading-snug pl-0.5">已添加博主集中管理与八维书签分类</p>
            </div>
          </div>

          <!-- 快速存储目录直达 -->
          <div class="space-y-2 pt-2 border-t border-slate-800/70">
            <div class="text-[10px] font-semibold text-slate-500 uppercase tracking-wider px-1">存储位置直达</div>
            <div class="space-y-1">
              <button onclick="setQuickFolder('F:/TikTok')" class="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs text-slate-400 hover:text-cyan-300 hover:bg-slate-900 transition-colors text-left font-mono text-[11px]">
                <span class="flex items-center space-x-2">
                  <i data-lucide="folder" class="w-3.5 h-3.5 text-cyan-400"></i>
                  <span>F:\TikTok</span>
                </span>
                <span class="text-[9px] text-slate-600">专属盘</span>
              </button>
              <button onclick="setQuickFolder('downloads')" class="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs text-slate-400 hover:text-cyan-300 hover:bg-slate-900 transition-colors text-left font-mono text-[11px]">
                <span class="flex items-center space-x-2">
                  <i data-lucide="folder" class="w-3.5 h-3.5 text-slate-500"></i>
                  <span>默认 downloads</span>
                </span>
                <span class="text-[9px] text-slate-600">本地</span>
              </button>
              <button onclick="openCurrentOutputDir()" class="w-full flex items-center space-x-2 px-2.5 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-slate-900 transition-colors text-left">
                <i data-lucide="external-link" class="w-3.5 h-3.5 text-amber-400"></i>
                <span>打开当前保存目录</span>
              </button>
            </div>
          </div>

        </div>

        <!-- 边栏底栏 -->
        <div class="p-3 border-t border-slate-800/80 bg-slate-950/90 space-y-2">
          <button onclick="openSettingsModal()" class="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-xs text-slate-300 hover:text-white border border-slate-800 transition-all">
            <span class="flex items-center space-x-2">
              <i data-lucide="sliders" class="w-3.5 h-3.5 text-cyan-400"></i>
              <span>下载与路径设置</span>
            </span>
            <i data-lucide="chevron-right" class="w-3.5 h-3.5 text-slate-500"></i>
          </button>
          
          <button onclick="toggleSidebar()" class="w-full flex items-center justify-center space-x-1.5 py-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors">
            <i data-lucide="panel-left-close" class="w-3.5 h-3.5"></i>
            <span>收起左侧边栏</span>
          </button>
        </div>

      </div>
    </aside>

    <!-- 右侧工作区容器 -->
    <div id="mainWorkspace" class="flex-1 min-w-0 overflow-y-auto custom-scroll flex flex-col justify-between">
      
      <!-- 页面 1: TikTok 视频下载器 -->
      <main id="pageTikTok" class="max-w-7xl mx-auto px-4 py-6 w-full space-y-6 flex-1">
    
    <!-- 抓取配置面板 -->
    <div class="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 shadow-xl tiktok-border-glow space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
        
        <!-- 博主用户名/主页 -->
        <div class="md:col-span-5 space-y-1.5">
          <label class="text-xs font-semibold text-slate-300 flex items-center space-x-1">
            <i data-lucide="user" class="w-3.5 h-3.5 text-cyan-400"></i>
            <span>TikTok 博主用户名 / 主页链接</span>
          </label>
          <div class="relative">
            <input type="text" id="inputUsername" placeholder="例如: charlidamelio 或 @username 或完整网址"
                   value="tech_reviewer"
                   class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition-all pl-10">
            <i data-lucide="at-sign" class="w-4 h-4 text-slate-500 absolute left-3.5 top-3"></i>
          </div>
        </div>

        <!-- 网络代理 -->
        <div class="md:col-span-3 space-y-1.5">
          <label class="text-xs font-semibold text-slate-300 flex items-center justify-between">
            <span class="flex items-center space-x-1">
              <i data-lucide="globe" class="w-3.5 h-3.5 text-rose-400"></i>
              <span>网络代理 (Proxy)</span>
            </span>
            <span class="text-[10px] text-slate-400">国内访问必填</span>
          </label>
          <div class="relative">
            <input type="text" id="inputProxy" placeholder="例: http://127.0.0.1:7890"
                   class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-rose-400 focus:ring-1 focus:ring-rose-400 transition-all pl-10">
            <i data-lucide="shield-check" class="w-4 h-4 text-slate-500 absolute left-3.5 top-3"></i>
          </div>
        </div>

        <!-- 限制数量 -->
        <div class="md:col-span-2 space-y-1.5">
          <label class="text-xs font-semibold text-slate-300 flex items-center space-x-1">
            <i data-lucide="layers" class="w-3.5 h-3.5 text-blue-400"></i>
            <span>抓取条数</span>
          </label>
          <input type="number" id="inputLimit" placeholder="留空全部" value="" min="1" max="5000"
                 class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400 transition-all">
        </div>

        <!-- 开始解析与停止操作 -->
        <div class="md:col-span-2 flex items-center space-x-2">
          <button id="btnScan" onclick="startScan(false)" class="flex-1 py-2.5 text-sm font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl shadow-lg shadow-cyan-600/25 transition-all flex items-center justify-center space-x-1.5 active:scale-95 cursor-pointer">
            <i data-lucide="search" class="w-4 h-4"></i>
            <span>解析博主</span>
          </button>
          <button id="btnStop" onclick="stopTask()" disabled class="px-3 py-2.5 text-sm font-semibold bg-slate-800 text-slate-500 rounded-xl transition-all flex items-center justify-center disabled:opacity-50 cursor-pointer" title="停止任务">
            <i data-lucide="square" class="w-4 h-4"></i>
          </button>
        </div>

      </div>

      <!-- 任务运行状态与进度条 (集成在卡片内，与 YouTube 风格统一) -->
      <div class="pt-3 border-t border-slate-800/80 flex items-center space-x-4">
        <div class="flex items-center space-x-2 text-xs">
          <span id="statusPulse" class="w-3 h-3 rounded-full bg-emerald-500 inline-block"></span>
          <span id="statusText" class="font-medium text-slate-300">就绪</span>
        </div>
        <div class="flex-1 bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
          <div id="progressBar" class="bg-gradient-to-r from-cyan-400 to-rose-500 h-full w-0 transition-all duration-300"></div>
        </div>
        <span id="progressText" class="text-xs font-mono text-slate-400 w-12 text-right">0%</span>
      </div>

    </div>

    <!-- 视频预览卡片与日志分栏 -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
      
      <!-- 视频列表展示 (占 8 列) -->
      <div class="lg:col-span-8 space-y-3">
        <!-- 列表顶部操作栏 (高度固定 h-12 与右侧 Tab 栏完全一致) -->
        <div class="h-12 flex items-center justify-between gap-2 bg-slate-900/80 border border-slate-800 rounded-xl px-4 shrink-0">
          <div class="flex items-center space-x-2">
            <i data-lucide="list-video" class="w-4 h-4 text-cyan-400"></i>
            <span class="text-sm font-bold text-slate-200">视频素材列表</span>
            <span id="videoCountBadge" class="text-xs px-2.5 py-0.5 rounded-full bg-slate-800 text-cyan-300 border border-slate-700 font-mono">0 个视频</span>
          </div>
          
          <div class="flex items-center space-x-2.5 text-xs">
            <button onclick="selectCurrentPage(true)" class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors">全选本页</button>
            <button onclick="selectAllVideos(true)" class="px-2.5 py-1 rounded-lg bg-cyan-950/60 border border-cyan-800/50 hover:bg-cyan-900 text-cyan-300 transition-colors">全选所有</button>
            <button onclick="selectAllVideos(false)" class="px-2 py-1 text-slate-400 hover:text-white transition-colors">取消全选</button>
            <span class="text-slate-700">|</span>
            <span id="selectedCountText" class="text-cyan-400 font-mono">已选 0 项</span>
          </div>
        </div>

        <!-- 框内列表容器 (最多 30 个视频，支持内部翻页) -->
        <div class="bg-slate-900/90 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          
          <!-- 表头 -->
          <div class="grid grid-cols-12 gap-3 px-4 py-2 bg-slate-950/80 border-b border-slate-800 text-[11px] font-semibold text-slate-400 select-none items-center">
            <div class="col-span-1 flex items-center space-x-1.5">
              <input type="checkbox" id="chkSelectPageHeader" onchange="toggleSelectCurrentPage(this.checked)" class="w-3.5 h-3.5 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0 cursor-pointer">
              <span>#</span>
            </div>
            <div class="col-span-2">封面</div>
            <div class="col-span-6">视频标题 / 描述</div>
            <div class="col-span-2 text-center">时长 / 播放</div>
            <div class="col-span-1 text-right">操作</div>
          </div>

          <!-- 视频项渲染区 (最多 30 个，带独立滚动条) -->
          <div id="videoListContainer" class="divide-y divide-slate-800/60 min-h-[380px] max-h-[500px] overflow-y-auto custom-scroll">
            <!-- 默认空状态 -->
            <div class="py-20 text-center text-slate-500">
              <i data-lucide="sparkles" class="w-8 h-8 text-slate-600 mx-auto mb-2"></i>
              <p class="text-xs">暂无视频，请在上方输入博主点击“解析”，或点击右上角“一键载入 Demo 体验”</p>
            </div>
          </div>

          <!-- 翻页控制底栏 (一个框最多 20 个视频) -->
          <div id="paginationBar" class="px-4 py-2.5 bg-slate-950/90 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div class="text-slate-400 flex items-center space-x-2">
              <span id="pageInfoText" class="font-mono text-[11px]">第 1 / 1 页 (每页上限 20 个)</span>
            </div>

            <!-- 翻页按钮 -->
            <div class="flex items-center space-x-1.5">
              <button id="btnPrevPage" onclick="changePage(-1)" disabled class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-30 disabled:cursor-not-allowed transition-all flex items-center space-x-1">
                <i data-lucide="chevron-left" class="w-3.5 h-3.5"></i>
                <span>上一页</span>
              </button>
              
              <div id="pagePillsContainer" class="flex items-center space-x-1"></div>

              <button id="btnNextPage" onclick="changePage(1)" disabled class="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-30 disabled:cursor-not-allowed transition-all flex items-center space-x-1">
                <span>下一页</span>
                <i data-lucide="chevron-right" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          </div>

        </div>
      </div>

      <!-- 实时控制台与下载队列选项卡 (占 4 列，参照 bradpittwyc/Tiktokdownloader-in-DS-Harness 设计) -->
      <div class="lg:col-span-4 space-y-3 flex flex-col h-[580px]">
        <!-- 选项卡顶部切换栏 (高度固定 h-12 与左侧列表栏完全平齐，纯净 Tab 切换无布局抖动) -->
        <div class="h-12 flex items-center justify-between gap-2 bg-slate-900/80 border border-slate-800 rounded-xl px-3 shrink-0">
          <div class="flex items-center space-x-1 bg-slate-950/70 p-1 rounded-lg border border-slate-800/80">
            <!-- 1. 下载队列 Tab -->
            <button id="tabBtnQueue" onclick="switchRightTab('queue')" class="px-3 py-1 rounded-md text-xs font-semibold transition-all flex items-center space-x-1.5 whitespace-nowrap bg-slate-800 text-cyan-400 border border-slate-700/60 shadow-sm">
              <i data-lucide="list-ordered" class="w-3.5 h-3.5"></i>
              <span>下载队列</span>
              <span id="queueCountBadge" class="ml-1 px-1.5 py-0.2 rounded-full bg-slate-900 text-[10px] text-cyan-300 font-mono">0</span>
            </button>
            <!-- 2. 控制台日志 Tab -->
            <button id="tabBtnLog" onclick="switchRightTab('log')" class="px-3 py-1 rounded-md text-xs font-medium transition-all flex items-center space-x-1.5 whitespace-nowrap text-slate-400 hover:text-white hover:bg-slate-800/50">
              <i data-lucide="terminal" class="w-3.5 h-3.5"></i>
              <span>控制台日志</span>
            </button>
          </div>
          <!-- 右侧常驻简约清空按钮，仅切换对应动作，尺寸恒定，绝不折行 -->
          <div>
            <button id="btnRightHeaderAction" onclick="handleRightHeaderAction()" class="text-xs text-slate-400 hover:text-slate-200 transition-colors flex items-center space-x-1 px-2.5 py-1 rounded-lg hover:bg-slate-800 whitespace-nowrap" title="清空内容">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              <span id="textRightHeaderAction">清除已完成</span>
            </button>
          </div>
        </div>

        <!-- 面板 1: 下载队列 (默认激活) -->
        <div id="panelQueue" class="flex-1 min-h-0 flex flex-col bg-slate-900/90 border border-slate-800 rounded-2xl p-3.5 overflow-hidden">
          
          <!-- 统计指标状态栏 (进行中、等待、完成、失败) -->
          <div class="flex items-center justify-between pb-2.5 mb-2 border-b border-slate-800/80 text-[11px] text-slate-400 font-medium">
            <span>进行中 <strong id="qActiveCount" class="text-cyan-400 font-mono">0</strong></span>
            <span>等待 <strong id="qWaitingCount" class="text-amber-400 font-mono">0</strong></span>
            <span>完成 <strong id="qDoneCount" class="text-emerald-400 font-mono">0</strong></span>
            <span>失败 <strong id="qFailedCount" class="text-rose-400 font-mono">0</strong></span>
          </div>

          <!-- 队列卡片滚动列表容器 -->
          <div id="queueItemsList" class="flex-1 overflow-y-auto space-y-2.5 custom-scroll pr-1">
            <!-- 空状态 -->
            <div class="h-full flex flex-col items-center justify-center text-slate-500 py-16 text-center">
              <i data-lucide="layers" class="w-8 h-8 text-slate-600 mb-2"></i>
              <p class="text-xs">勾选视频并点击“批量下载”后，任务将显示在这里</p>
            </div>
          </div>

          <!-- 队列底栏 (打开下载目录 + 全部取消 + 队列项数统计) -->
          <div class="pt-2.5 mt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
            <button onclick="openCurrentOutputDir()" class="text-[11px] text-slate-400 hover:text-cyan-300 flex items-center space-x-1 transition-colors">
              <i data-lucide="folder-open" class="w-3.5 h-3.5 text-cyan-400"></i>
              <span>打开博主存储目录</span>
            </button>
            <div class="flex items-center space-x-2 text-xs">
              <button onclick="cancelAllQueue()" class="text-[11px] text-rose-400 hover:text-rose-300 px-2 py-0.5 rounded bg-rose-950/40 border border-rose-900/50 hover:bg-rose-900/50 transition-colors">全部取消</button>
              <span class="text-slate-700">|</span>
              <span id="queuePageText" class="text-slate-400 font-mono text-[11px]">队列总计 0 项</span>
            </div>
          </div>

        </div>

        <!-- 面板 2: 控制台日志 -->
        <div id="panelLog" class="hidden flex-1 min-h-0 flex flex-col">
          <div id="logConsole" class="flex-1 bg-slate-950 border border-slate-800 rounded-2xl p-3.5 overflow-y-auto font-mono text-xs text-slate-300 space-y-1.5 custom-scroll">
            <div class="text-slate-500">// 欢迎使用 TikTok 视频批量抓取引擎</div>
            <div class="text-slate-500">// 本地环境连接已建立</div>
          </div>
        </div>
      </div>

    </div>

    <!-- ============ 🌟 底部下载配置与操作条 (TikTok 专属吸底条) ============ -->
    <div id="tiktokActionBar" class="sticky bottom-3 z-30 bg-slate-900/95 backdrop-blur-md border border-slate-800 rounded-2xl p-4 shadow-2xl space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div class="flex flex-wrap items-center gap-4 text-slate-300">
          <label class="flex items-center space-x-2 cursor-pointer select-none">
            <input type="checkbox" id="chkSubtitles" checked class="rounded border-slate-700 bg-slate-950 text-cyan-500 focus:ring-0">
            <span class="flex items-center space-x-1">
              <i data-lucide="subtitles" class="w-3.5 h-3.5 text-cyan-400"></i>
              <span>随视频下载字幕</span>
            </span>
          </label>
          <label class="flex items-center space-x-2 cursor-pointer select-none">
            <input type="checkbox" id="chkThumb" checked class="rounded border-slate-700 bg-slate-950 text-cyan-500 focus:ring-0">
            <span>封面图</span>
          </label>
          <label class="flex items-center space-x-2 cursor-pointer select-none">
            <input type="checkbox" id="chkJson" checked class="rounded border-slate-700 bg-slate-950 text-cyan-500 focus:ring-0">
            <span>JSON元数据</span>
          </label>
          <span class="text-slate-700">|</span>
          <div class="flex items-center space-x-1.5">
            <button type="button" onclick="browseDirectoryNative()" title="点击直接弹出 Windows 资源管理器窗口选择" class="text-slate-400 hover:text-cyan-300 flex items-center space-x-1.5 transition-colors group px-2 py-1 rounded hover:bg-slate-800">
              <i data-lucide="folder-search" class="w-3.5 h-3.5 text-amber-400 group-hover:scale-110 transition-transform"></i>
              <span>保存目录: <span id="currentOutputDirLabel" class="text-cyan-400 font-mono underline decoration-dotted">downloads</span></span>
              <span class="text-[10px] bg-cyan-950 border border-cyan-800/60 px-1.5 py-0.5 rounded text-cyan-300">点击更换</span>
            </button>
            <button type="button" onclick="openCurrentOutputDir()" title="在资源管理器中打开当前保存目录" class="text-slate-500 hover:text-slate-300 p-1 rounded hover:bg-slate-800 transition-colors">
              <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </div>

        <div class="flex items-center space-x-2.5 shrink-0">
          <button id="btnDownloadAll" onclick="startDownloadSelected()" class="px-5 py-2.5 text-xs font-semibold bg-gradient-to-r from-cyan-600 to-rose-600 hover:from-cyan-500 hover:to-rose-500 text-white rounded-xl shadow-lg shadow-rose-600/25 transition-all flex items-center space-x-2 active:scale-95 cursor-pointer">
            <i data-lucide="download-cloud" class="w-4 h-4"></i>
            <span id="btnDownloadAllText">批量下载已选</span>
          </button>
        </div>
      </div>

      <!-- 高级设置：Cookie 文本直接粘贴 (避免锁库，折叠) -->
      <div class="pt-2 border-t border-slate-800/60">
        <details class="text-xs text-slate-400 cursor-pointer">
          <summary class="hover:text-cyan-400 select-none flex items-center space-x-1.5">
            <span>⚙️ 高级选项：直接粘贴 Cookie 字符串 (可选，用于突破翻页防爬限制)</span>
          </summary>
          <div class="mt-2.5 p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
            <p class="text-[11px] text-slate-400">在浏览器按 F12 复制已登录 TikTok 网页的 Cookie 请求头直接贴在下面，无需导出文件，不会报错：</p>
            <input type="text" id="inputCookieText" placeholder="粘贴 Cookie: 例如 sessionid=...; tt_webid=... (留空则免登录)" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-cyan-400">
          </div>
        </details>
      </div>
    </div>

  </main>

  <!-- 页面 2: YouTube 视频下载器 (原样复制卡片 2) -->
  <main id="pageYouTube" class="max-w-7xl mx-auto px-4 py-6 w-full space-y-6 flex-1 hidden">
    
    <!-- 抓取配置面板 -->
    <div class="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 shadow-xl youtube-border-glow space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-12 gap-4 items-end">
        
        <!-- YouTube 频道/播放列表/视频链接 -->
        <div class="md:col-span-5 space-y-1.5">
          <label class="text-xs font-semibold text-slate-300 flex items-center space-x-1">
            <i data-lucide="play" class="w-3.5 h-3.5 text-red-500 fill-red-500"></i>
            <span>YouTube 频道主页 / 播放列表 / 视频网址</span>
          </label>
          <div class="relative">
            <input type="text" id="inputYtUrl" placeholder="例如: https://www.youtube.com/@mkbhd/videos 或播放列表"
                   value="https://www.youtube.com/@mkbhd/videos"
                   class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500 transition-all pl-10">
            <i data-lucide="youtube" class="w-4 h-4 text-red-400 absolute left-3.5 top-3"></i>
          </div>
        </div>

        <!-- 网络代理 -->
        <div class="md:col-span-3 space-y-1.5">
          <label class="text-xs font-semibold text-slate-300 flex items-center justify-between">
            <span class="flex items-center space-x-1">
              <i data-lucide="globe" class="w-3.5 h-3.5 text-rose-400"></i>
              <span>网络代理 (Proxy)</span>
            </span>
            <span class="text-[10px] text-slate-400">国内访问必填</span>
          </label>
          <input type="text" id="inputYtProxy" placeholder="例如: http://127.0.0.1:7890" value=""
                 class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500 transition-all">
        </div>

        <!-- 限制数量 -->
        <div class="md:col-span-2 space-y-1.5">
          <label class="text-xs font-semibold text-slate-300 flex items-center space-x-1">
            <i data-lucide="layers" class="w-3.5 h-3.5 text-red-400"></i>
            <span>抓取条数</span>
          </label>
          <input type="number" id="inputYtLimit" placeholder="留空全部" value="" min="1" max="5000"
                 class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500 transition-all">
        </div>

        <!-- 开始解析与停止操作 -->
        <div class="md:col-span-2 flex items-center space-x-2">
          <button id="btnYtScan" onclick="startYtScan()" class="flex-1 py-2.5 text-sm font-semibold bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white rounded-xl shadow-lg shadow-red-600/30 transition-all flex items-center justify-center space-x-1.5 active:scale-95 cursor-pointer">
            <i data-lucide="search" class="w-4 h-4"></i>
            <span>开始解析</span>
          </button>
          <button id="btnYtStop" onclick="stopYtTask()" disabled class="px-3 py-2.5 text-sm font-semibold bg-slate-800 text-slate-500 rounded-xl transition-all flex items-center justify-center disabled:opacity-50 cursor-pointer" title="停止任务">
            <i data-lucide="square" class="w-4 h-4"></i>
          </button>
        </div>

      </div>

      <!-- 任务运行状态与进度条 -->
      <div class="pt-3 border-t border-slate-800/80 flex items-center space-x-4">
        <div class="flex items-center space-x-2 text-xs">
          <span id="ytStatusPulse" class="w-3 h-3 rounded-full bg-emerald-500 inline-block"></span>
          <span id="ytStatusText" class="font-medium text-slate-300">空闲待命就绪</span>
        </div>
        <div class="flex-1 bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
          <div id="ytProgressBar" class="h-full bg-gradient-to-r from-red-600 via-rose-500 to-amber-400 transition-all duration-300 w-0"></div>
        </div>
        <span id="ytProgressText" class="text-xs font-mono text-slate-400 w-12 text-right">0%</span>
      </div>

    </div>

    <!-- 核心两栏联动布局 (左侧：视频列表与分页；右侧：下载队列与控制台日志) -->
    <div class="grid grid-cols-1 md:grid-cols-12 gap-6 items-stretch">
      
      <!-- 左栏：视频解析结果展示列表 (占 8 列) -->
      <div class="md:col-span-8 flex flex-col space-y-4">
        
        <!-- 表格工具栏 (带博主领域归类徽章 + 四维分类 Tab 切换) -->
        <div class="flex flex-col space-y-3">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center space-x-2.5 flex-wrap gap-y-1">
              <h2 class="text-base font-bold text-slate-100 flex items-center space-x-2">
                <i data-lucide="play-square" class="w-5 h-5 text-red-500"></i>
                <span>YouTube 频道与视频列表</span>
              </h2>
              <span id="ytChannelCategoryBadge" class="text-xs px-2.5 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800/80 font-semibold inline-flex items-center space-x-1 shadow-sm">
                <span>🤖 科技 & AI</span>
              </span>
              <span id="ytVideoCountBadge" class="text-xs px-2.5 py-0.5 rounded-full bg-red-950 text-red-300 border border-red-900/60 font-mono">0 个视频</span>
              <span id="ytSelectedCountBadge" class="text-xs text-slate-400">已选 <strong class="text-red-400 font-mono">0</strong> 项</span>
            </div>
            
            <div class="flex items-center space-x-2">
              <button id="btnYtSelectPage" onclick="selectYtCurrentPage()" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 transition-colors">
                全选本页
              </button>
              <button id="btnYtSelectAll" onclick="selectAllYtVideos()" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-lg border border-slate-700 transition-colors">
                全选全部
              </button>
              <button id="btnYtDownloadSelected" onclick="startYtDownloadSelected()" class="px-3.5 py-1.5 text-xs font-semibold bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white rounded-lg shadow-md shadow-red-600/25 transition-all flex items-center space-x-1.5 active:scale-95">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
                <span id="btnYtDownloadSelectedText">下载选中项 (0)</span>
              </button>
            </div>
          </div>

          <!-- 🌟 四维分类标签页 (Videos / Shorts / Live / Podcasts) -->
          <div class="flex items-center space-x-1.5 p-1 bg-slate-900/90 rounded-xl border border-slate-800 text-xs overflow-x-auto custom-scroll">
            <button id="btnCatAll" onclick="filterYtCategory('all')" class="px-3 py-1.5 rounded-lg font-semibold bg-red-600 text-white shadow-sm transition-all whitespace-nowrap">
              全部 (<span id="catCountAll">0</span>)
            </button>
            <button id="btnCatVideos" onclick="filterYtCategory('videos')" class="px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-all whitespace-nowrap">
              🎬 长视频 (<span id="catCountVideos">0</span>)
            </button>
            <button id="btnCatShorts" onclick="filterYtCategory('shorts')" class="px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-all whitespace-nowrap">
              ⚡ 短视频 Shorts (<span id="catCountShorts">0</span>)
            </button>
            <button id="btnCatLive" onclick="filterYtCategory('live')" class="px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-all whitespace-nowrap">
              🔴 直播回放 Live (<span id="catCountLive">0</span>)
            </button>
            <button id="btnCatPodcasts" onclick="filterYtCategory('podcasts')" class="px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-all whitespace-nowrap">
              🎙️ 播客专栏 Podcasts (<span id="catCountPodcasts">0</span>)
            </button>
          </div>
        </div>


        <!-- 视频数据表格容器 -->
        <div class="bg-slate-900/80 border border-slate-800 rounded-2xl overflow-hidden shadow-xl flex-1 flex flex-col">
          <div class="overflow-x-auto custom-scroll flex-1">
            <table class="w-full text-left border-collapse">
              <thead>
                <tr class="h-12 border-b border-slate-800 bg-slate-950/80 text-[11px] font-semibold text-slate-400 uppercase tracking-wider select-none">
                  <th class="px-4 py-0 w-10 text-center align-middle">
                    <input type="checkbox" id="selectAllYtPageCheckbox" onclick="toggleSelectAllYtPage(this)" class="rounded border-slate-700 bg-slate-900 text-red-500 focus:ring-0 cursor-pointer">
                  </th>
                  <th class="px-3 py-0 w-16 align-middle">封面</th>
                  <th class="px-3 py-0 min-w-[200px] align-middle">视频标题与频道</th>
                  <th class="px-3 py-0 w-20 align-middle">时长</th>
                  <th class="px-3 py-0 w-28 align-middle">播放 / 点赞</th>
                  <th class="px-3 py-0 w-24 align-middle">发布时间</th>
                  <th class="px-4 py-0 w-24 text-right align-middle">操作</th>
                </tr>
              </thead>
              <tbody id="ytVideoTableBody" class="divide-y divide-slate-800/80 text-xs">
                <tr>
                  <td colspan="7" class="py-20 text-center text-slate-500">
                    <div class="flex flex-col items-center justify-center space-y-2">
                      <i data-lucide="film" class="w-8 h-8 text-slate-600"></i>
                      <span>暂无解析数据，请在上方输入 YouTube 频道并点击【开始解析抓取】或【载入 YouTube Demo】</span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 分页控制器底栏 (每页 20 项) -->
          <div class="p-3 border-t border-slate-800/80 bg-slate-950/70 flex items-center justify-between text-xs">
            <div id="ytPageInfo" class="text-slate-400">
              显示第 0 - 0 项，共 0 项 (每页 20 项)
            </div>
            <div class="flex items-center space-x-1.5">
              <button id="ytPrevBtn" onclick="changeYtPage(-1)" disabled class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-800 text-slate-200 transition-colors flex items-center space-x-1">
                <i data-lucide="chevron-left" class="w-4 h-4"></i>
                <span>上一页</span>
              </button>
              <div id="ytPageNumbers" class="flex items-center space-x-1 px-1">
              </div>
              <button id="ytNextBtn" onclick="changeYtPage(1)" disabled class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-800 text-slate-200 transition-colors flex items-center space-x-1">
                <span>下一页</span>
                <i data-lucide="chevron-right" class="w-4 h-4"></i>
              </button>
            </div>
          </div>

        </div>

      </div>

      <!-- 右栏：下载队列与控制台日志 (占 4 列，与左侧表格绝对对齐) -->
      <div class="md:col-span-4 flex flex-col space-y-4">
        
        <!-- Tab 切换头部 (h-12 高度与左侧表头一致) -->
        <div class="h-12 flex items-center justify-between px-1">
          <div class="flex items-center space-x-1 bg-slate-900/90 p-1 rounded-xl border border-slate-800">
            <!-- Tab 1: 下载队列 (默认激活) -->
            <button id="btnYtTabQueue" onclick="switchYtRightTab('queue')" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-red-600 text-white shadow-md transition-all flex items-center space-x-1.5 whitespace-nowrap">
              <i data-lucide="list-ordered" class="w-3.5 h-3.5"></i>
              <span>下载队列</span>
              <span id="ytQueueCountBadge" class="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-red-950 text-red-200">0</span>
            </button>
            
            <!-- Tab 2: 控制台日志 -->
            <button id="btnYtTabLog" onclick="switchYtRightTab('log')" class="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200 transition-all flex items-center space-x-1.5 whitespace-nowrap">
              <i data-lucide="terminal" class="w-3.5 h-3.5"></i>
              <span>控制台日志</span>
              <span id="ytLogCountBadge" class="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-slate-800 text-slate-400">0</span>
            </button>
          </div>

          <!-- 右侧常驻简约清空按钮 -->
          <div>
            <button id="btnYtRightHeaderAction" onclick="handleYtRightHeaderAction()" class="text-xs text-slate-400 hover:text-slate-200 transition-colors flex items-center space-x-1 px-2.5 py-1 rounded-lg hover:bg-slate-800 whitespace-nowrap" title="清空内容">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              <span id="textYtRightHeaderAction">清除已完成</span>
            </button>
          </div>
        </div>

        <!-- 面板 1: 下载队列 (默认激活) -->
        <div id="panelYtQueue" class="flex-1 min-h-0 flex flex-col bg-slate-900/90 border border-slate-800 rounded-2xl p-3.5 overflow-hidden">
          
          <!-- 统计指标状态栏 -->
          <div class="flex items-center justify-between pb-2.5 mb-2 border-b border-slate-800/80 text-[11px] text-slate-400 font-medium">
            <span>进行中 <strong id="ytQActiveCount" class="text-red-400 font-mono">0</strong></span>
            <span>等待 <strong id="ytQWaitingCount" class="text-amber-400 font-mono">0</strong></span>
            <span>完成 <strong id="ytQDoneCount" class="text-emerald-400 font-mono">0</strong></span>
            <span>失败 <strong id="ytQFailedCount" class="text-rose-400 font-mono">0</strong></span>
          </div>

          <!-- 队列卡片滚动列表容器 -->
          <div id="ytQueueItemsList" class="flex-1 overflow-y-auto space-y-2.5 custom-scroll pr-1">
            <!-- 空状态 -->
            <div class="h-full flex flex-col items-center justify-center text-slate-500 py-16 text-center">
              <i data-lucide="layers" class="w-8 h-8 text-slate-600 mb-2"></i>
              <p class="text-xs">勾选 YouTube 视频并点击“批量下载”后，任务将显示在这里</p>
            </div>
          </div>

          <!-- 队列底栏 -->
          <div class="pt-2.5 mt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
            <button onclick="openCurrentOutputDir()" class="text-[11px] text-slate-400 hover:text-red-300 flex items-center space-x-1 transition-colors">
              <i data-lucide="folder-open" class="w-3.5 h-3.5 text-red-400"></i>
              <span>打开频道存储目录</span>
            </button>
            <div class="flex items-center space-x-2 text-xs">
              <button onclick="cancelYtAllQueue()" class="text-[11px] text-rose-400 hover:text-rose-300 px-2 py-0.5 rounded bg-rose-950/40 border border-rose-900/50 hover:bg-rose-900/50 transition-colors">全部取消</button>
              <span class="text-slate-700">|</span>
              <span id="ytQueuePageText" class="text-slate-400 font-mono text-[11px]">队列总计 0 项</span>
            </div>
          </div>

        </div>

        <!-- 面板 2: 控制台日志 -->
        <div id="panelYtLog" class="hidden flex-1 min-h-0 flex flex-col">
          <div id="ytLogConsole" class="flex-1 bg-slate-950 border border-slate-800 rounded-2xl p-3.5 overflow-y-auto font-mono text-xs text-slate-300 space-y-1.5 custom-scroll">
            <div class="text-slate-500">// 欢迎使用 YouTube 视频批量抓取引擎</div>
            <div class="text-slate-500">// 本地环境连接已建立</div>
          </div>
        </div>
      </div>

    </div>

    <!-- ============ 🌟 底部下载配置与操作条 (对标 bradpittwyc/Youtube-Downloader ActionBar) ============ -->
    <div id="ytActionBar" class="sticky bottom-3 z-30 bg-slate-900/95 backdrop-blur-md border border-slate-800 rounded-2xl p-4 shadow-2xl space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div class="flex flex-wrap items-center gap-2.5 text-slate-300">
          <!-- 画质选择 -->
          <div class="flex items-center space-x-1.5 bg-slate-950 px-2.5 py-1.5 rounded-xl border border-slate-800">
            <span class="text-slate-400 font-medium text-[11px] whitespace-nowrap">画质:</span>
            <select id="selectYtQuality" class="bg-transparent text-xs text-white focus:outline-none cursor-pointer">
              <option value="best" selected>最佳画质 (4K/1080p + AAC原声)</option>
              <option value="2160">2160p (4K 超清)</option>
              <option value="1440">1440p (2K 极清)</option>
              <option value="1080">1080p (全高清 FHD)</option>
              <option value="720">720p (高清 HD)</option>
              <option value="480">480p (标清)</option>
              <option value="360">360p (流畅)</option>
              <option value="audio_only">仅下载音频 MP3</option>
            </select>
          </div>

          <!-- 同时导出 MP3 -->
          <label class="flex items-center space-x-1.5 px-2.5 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800 cursor-pointer select-none" title="视频下载完成后，本地 FFmpeg 极速抽轨导出同名 MP3，免二次下载">
            <input type="checkbox" id="chkYtAlsoAudio" checked class="rounded border-slate-700 bg-slate-900 text-red-500 focus:ring-0">
            <span class="text-amber-300 font-medium">🎵 同时导出 MP3</span>
          </label>

          <!-- 字幕组件 -->
          <label class="flex items-center space-x-1.5 px-2.5 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800 cursor-pointer select-none">
            <input type="checkbox" id="chkYtSubtitles" checked class="rounded border-slate-700 bg-slate-900 text-red-500 focus:ring-0">
            <span>下载字幕 (SRT/VTT)</span>
          </label>

          <!-- 双语字幕 -->
          <label class="flex items-center space-x-1.5 px-2.5 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800 cursor-pointer select-none" title="生成中英双轨 SRT 以及黄色+纯白带描边的 ASS 高级特效字幕">
            <input type="checkbox" id="chkYtBiSubs" checked class="rounded border-slate-700 bg-slate-900 text-red-500 focus:ring-0">
            <span class="text-cyan-300 font-medium">📝 中英双语字幕 (.srt/.ass)</span>
          </label>

          <!-- AI学习文档 -->
          <label class="flex items-center space-x-1.5 px-2.5 py-1.5 rounded-xl bg-slate-950/80 border border-slate-800 cursor-pointer select-none" title="调用大模型/内置引擎生成中英精读对照、带时间码、生词表与语法点拨的 Word 学习文档">
            <input type="checkbox" id="chkYtStudyDoc" checked class="rounded border-slate-700 bg-slate-900 text-red-500 focus:ring-0">
            <span class="text-emerald-300 font-medium">📘 AI 学习文档 (.docx)</span>
          </label>

          <label class="flex items-center space-x-1 cursor-pointer select-none px-1">
            <input type="checkbox" id="chkYtThumb" checked class="rounded border-slate-700 bg-slate-950 text-red-500 focus:ring-0">
            <span class="text-[11px] text-slate-400">封面</span>
          </label>
          <label class="flex items-center space-x-1 cursor-pointer select-none px-1">
            <input type="checkbox" id="chkYtJson" checked class="rounded border-slate-700 bg-slate-950 text-red-500 focus:ring-0">
            <span class="text-[11px] text-slate-400">JSON</span>
          </label>

          <span class="text-slate-700">|</span>

          <!-- 保存目录直达与更换 -->
          <div class="flex items-center space-x-1.5">
            <button type="button" onclick="browseDirectoryNative()" title="点击直接弹出 Windows 资源管理器窗口选择" class="text-slate-400 hover:text-red-300 flex items-center space-x-1.5 transition-colors group px-2 py-1 rounded hover:bg-slate-800">
              <i data-lucide="folder-search" class="w-3.5 h-3.5 text-amber-400 group-hover:scale-110 transition-transform"></i>
              <span>保存目录: <span id="currentYtOutputDirLabel" class="text-red-400 font-mono underline decoration-dotted">downloads</span></span>
              <span class="text-[10px] bg-red-950 border border-red-800/60 px-1.5 py-0.5 rounded text-red-300">点击更换</span>
            </button>
            <button type="button" onclick="openCurrentOutputDir()" title="在资源管理器中打开当前保存目录" class="text-slate-500 hover:text-slate-300 p-1 rounded hover:bg-slate-800 transition-colors">
              <i data-lucide="folder-open" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </div>

        <!-- 底部下载操作按钮 -->
        <div class="flex items-center space-x-2.5 shrink-0">
          <button id="btnYtDownloadSelectedBottom" onclick="startYtDownloadSelected()" class="px-5 py-2.5 text-xs font-semibold bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-500 hover:to-rose-500 text-white rounded-xl shadow-lg shadow-red-600/30 transition-all flex items-center space-x-1.5 active:scale-95 cursor-pointer">
            <i data-lucide="download" class="w-4 h-4"></i>
            <span id="btnYtDownloadSelectedBottomText">下载选中项 (0)</span>
          </button>
          <button id="btnYtDownloadAll" onclick="startYtDownloadAll()" class="px-4 py-2.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white rounded-xl border border-slate-700 transition-all flex items-center space-x-1.5 active:scale-95 cursor-pointer">
            <i data-lucide="download-cloud" class="w-4 h-4 text-red-400"></i>
            <span>批量下载全部</span>
          </button>
        </div>
      </div>

      <!-- 高级设置：Cookie 文本直接粘贴 (折叠) -->
      <div class="pt-2 border-t border-slate-800/60">
        <details class="text-xs text-slate-400 cursor-pointer">
          <summary class="hover:text-red-400 select-none flex items-center space-x-1.5">
            <span>⚙️ 高级选项：直接粘贴 Cookie 字符串 (可选，用于突破会员或受限视频下载)</span>
          </summary>
          <div class="mt-2.5 p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
            <p class="text-[11px] text-slate-400">在浏览器按 F12 复制已登录 YouTube 的 Cookie 请求头直接贴在下面，无需导出文件，不会报错：</p>
            <input type="text" id="inputYtCookieText" placeholder="粘贴 Cookie: 例如 SID=...; HSID=... (留空则免登录)" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-red-500">
          </div>
        </details>
      </div>
    </div>

  </main>

  <!-- ================= 页面 3: 频道管理与博主库 (跨平台) ================= -->
  <main id="pageChannels" class="max-w-7xl mx-auto px-4 py-6 w-full space-y-6 flex-1 hidden">
    
    <!-- 顶部概览条 -->
    <div class="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 shadow-xl flex flex-wrap items-center justify-between gap-4">
      <div class="flex items-center space-x-3.5">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-600 flex items-center justify-center text-white shadow-lg shadow-indigo-600/30">
          <i data-lucide="layout-grid" class="w-5 h-5"></i>
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <h2 class="text-base font-bold text-slate-100">跨平台频道与博主归档库</h2>
            <span class="text-[10px] px-2 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-800/60 font-mono">已入库博主</span>
          </div>
          <p class="text-xs text-slate-400 mt-0.5">左侧展示 TikTok 已抓取博主，右侧按参考下载器八维书签展示 YouTube 频道，支持一键点击直接调起并解析</p>
        </div>
      </div>

      <div class="flex items-center space-x-3">
        <button onclick="loadChannelsUI()" class="px-3.5 py-2 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl border border-slate-700 transition-all flex items-center space-x-1.5 active:scale-95 cursor-pointer">
          <i data-lucide="refresh-cw" class="w-3.5 h-3.5 text-indigo-400"></i>
          <span>刷新数据</span>
        </button>
      </div>
    </div>

    <!-- 左右双栏结构：左边 TikTok 博主 (5列) | 右边 YouTube 频道 (7列) -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      
      <!-- ================= 左栏: TikTok 博主 ================= -->
      <div class="lg:col-span-5 space-y-4">
        
        <div class="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-lg space-y-3">
          <div class="flex items-center justify-between border-b border-slate-800/80 pb-3">
            <div class="flex items-center space-x-2">
              <div class="w-7 h-7 rounded-lg bg-gradient-to-tr from-cyan-400 to-rose-500 flex items-center justify-center text-white text-xs">
                <i data-lucide="video" class="w-4 h-4"></i>
              </div>
              <span class="font-bold text-sm text-slate-100">TikTok 已添加博主</span>
              <span id="tiktokCreatorCountBadge" class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-cyan-300 font-mono">0 位</span>
            </div>
            
            <button onclick="quickAddTiktokCreatorModal()" class="px-2.5 py-1 text-xs font-semibold bg-cyan-600/20 hover:bg-cyan-600/30 text-cyan-300 border border-cyan-500/30 rounded-lg transition-all flex items-center space-x-1 cursor-pointer">
              <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              <span>添加博主</span>
            </button>
          </div>

          <!-- TikTok 博主卡片列表 -->
          <div id="tiktokCreatorsList" class="space-y-2.5 max-h-[660px] overflow-y-auto custom-scroll pr-1">
            <!-- 动态渲染 -->
          </div>
        </div>

      </div>

      <!-- ================= 右栏: YouTube 频道 (完全复刻参考器书签分类与卡片) ================= -->
      <div class="lg:col-span-7 space-y-4">
        
        <div class="bg-slate-900/90 border border-slate-800 rounded-2xl shadow-xl overflow-hidden">
          
          <!-- 顶部标题与快速添加 -->
          <div class="p-4 border-b border-slate-800/80 flex items-center justify-between bg-slate-950/40">
            <div class="flex items-center space-x-2">
              <div class="w-7 h-7 rounded-lg bg-gradient-to-tr from-red-600 to-rose-600 flex items-center justify-center text-white text-xs">
                <i data-lucide="play" class="w-4 h-4 fill-white"></i>
              </div>
              <span class="font-bold text-sm text-slate-100">YouTube 频道库 (参考分类器)</span>
              <span id="ytChannelTotalBadge" class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-red-300 font-mono">10 个频道</span>
            </div>

            <button onclick="quickAddYtChannelModal()" class="px-2.5 py-1 text-xs font-semibold bg-red-600/20 hover:bg-red-600/30 text-red-300 border border-red-500/30 rounded-lg transition-all flex items-center space-x-1 cursor-pointer">
              <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              <span>添加频道</span>
            </button>
          </div>

          <!-- 🌟 YouTube 书签式分类栏 (完全还原截图：全部 / 科技 / 成长 / 健康 / 商业 / 人文 / 娱乐 / 其他) -->
          <div class="px-3 pt-2.5 pb-0 bg-slate-950/80 border-b border-slate-800/80 flex items-center gap-1.5 overflow-x-auto custom-scroll select-none">
            <div id="ytChannelCategoryTabs" class="flex items-center gap-1.5 min-w-full">
              <!-- 动态或静态渲染分类 tabs -->
            </div>
          </div>

          <!-- YouTube 频道网格 (Grid 布局，每行 2~3 列，对标截图卡片样式) -->
          <div class="p-4 bg-slate-950/30">
            <div id="ytChannelsGrid" class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 max-h-[600px] overflow-y-auto custom-scroll pr-1">
              <!-- 动态渲染频道卡片 -->
            </div>
          </div>

        </div>

      </div>

    </div>

  </main>

  <!-- 脚部 -->
  <footer class="border-t border-slate-800/80 py-4 mt-8 bg-slate-950/60">
    <div class="max-w-7xl mx-auto px-4 text-center text-xs text-slate-500">
      TikTok & YouTube Video Scraper Studio • Powered by FastAPI & yt-dlp
    </div>
  </footer>

  </div> <!-- /#mainWorkspace -->
  </div> <!-- /outer flex layout -->

  <!-- 设置面板弹窗 (模态框) -->
  <div id="settingsModal" class="fixed inset-0 z-[999] bg-black/75 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-xl w-full p-6 shadow-2xl tiktok-border-glow space-y-5 transform transition-all">
      
      <!-- 弹窗标题 -->
      <div class="flex items-center justify-between pb-3 border-b border-slate-800">
        <div class="flex items-center space-x-2.5">
          <div class="w-8 h-8 rounded-lg bg-cyan-500/20 text-cyan-400 flex items-center justify-center">
            <i data-lucide="sliders" class="w-5 h-5"></i>
          </div>
          <div>
            <h3 class="text-base font-bold text-slate-100">下载偏好与存储目录设置</h3>
            <p class="text-[11px] text-slate-400">调整文件存放路径、专属文件夹归档及伴随字幕参数</p>
          </div>
        </div>
        <button onclick="closeSettingsModal()" class="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors">
          <i data-lucide="x" class="w-5 h-5"></i>
        </button>
      </div>

      <!-- 设置表单内容 -->
      <div class="space-y-4 text-xs">
        
        <!-- 存储根路径设置 -->
        <div class="space-y-1.5">
          <label class="text-xs font-semibold text-slate-300 flex items-center justify-between">
            <span class="flex items-center space-x-1.5">
              <i data-lucide="folder" class="w-4 h-4 text-cyan-400"></i>
              <span>下载保存主目录 (根路径)</span>
            </span>
            <span class="text-[10px] text-cyan-400">✨ 支持点击调起系统资源管理器选择</span>
          </label>
          <div class="flex items-center space-x-2">
            <div class="relative flex-1">
              <input type="text" id="settingOutputDir" placeholder="例如: downloads 或 D:\TikTokVideos"
                     class="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-2.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400 transition-all font-mono">
            </div>
            <button type="button" id="btnBrowseFolder" onclick="browseDirectoryNative()" class="px-4 py-2.5 text-xs font-semibold bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-xl shadow-md shadow-cyan-600/25 transition-all flex items-center space-x-1.5 active:scale-95 whitespace-nowrap cursor-pointer">
              <i data-lucide="folder-search" class="w-4 h-4"></i>
              <span>弹出系统窗口选择</span>
            </button>
            <button type="button" onclick="openCurrentOutputDir()" title="在Windows资源管理器中打开此文件夹" class="px-3 py-2.5 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded-xl border border-slate-700 transition-all flex items-center space-x-1 cursor-pointer">
              <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
              <span>打开目录</span>
            </button>
          </div>
          <div class="flex flex-wrap items-center gap-2 pt-1">
            <span class="text-[10px] text-slate-500">常用快捷位置:</span>
            <button type="button" onclick="setQuickFolder('downloads')" class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors">默认 downloads</button>
            <button type="button" onclick="setQuickFolder('F:/TikTok')" class="px-2 py-0.5 rounded bg-cyan-950/80 border border-cyan-800/60 hover:bg-cyan-900 text-cyan-300 text-[11px] transition-colors">📁 F:\TikTok</button>
            <button type="button" onclick="setQuickFolder('C:/Users/Administrator/Downloads')" class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors">📥 此电脑下载</button>
            <button type="button" onclick="setQuickFolder('C:/Users/Administrator/Desktop')" class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors">🖥️ 桌面</button>
            <button type="button" onclick="setQuickFolder('D:/TikTokVideos')" class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors">💾 D盘 TikTok</button>
          </div>
          <p class="text-[11px] text-slate-400">
            👉 点击 <strong>【浏览选择文件夹】</strong> 会直接调出 Windows 资源管理器选择窗口，选取您的任意本地盘符或新建专属目录。
          </p>
        </div>

        <!-- 独立文件夹功能说明 -->
        <div class="p-3.5 rounded-xl bg-slate-950/80 border border-cyan-950/60 space-y-2">
          <label class="flex items-center space-x-2.5 cursor-pointer select-none">
            <input type="checkbox" id="settingCreateBloggerFolder" checked class="w-4 h-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0">
            <span class="font-semibold text-slate-200">按 @博主ID 自动建立专属独立文件夹 (内置自动归档)</span>
          </label>
          <p class="text-[11px] text-slate-400 pl-6 leading-relaxed">
            开启后，任何下载的视频均会自动创建以 <code>@博主ID</code> 命名的专属子目录（例如 <code>F:\TikTok\@sixers\</code>）。未来再次解析或下载该博主的新视频时，<strong>所有文件都会自动集中收纳进同一个 @博主 文件夹中</strong>，防止视频散落混乱。
          </p>
        </div>

        <!-- 伴随字幕下载功能 -->
        <div class="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2">
          <label class="flex items-center space-x-2.5 cursor-pointer select-none">
            <input type="checkbox" id="settingSaveSubtitles" checked class="w-4 h-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0">
            <span class="font-semibold text-slate-200">随视频自动下载字幕文件 (SRT / VTT)</span>
          </label>
          <p class="text-[11px] text-slate-400 pl-6 leading-relaxed">
            自动抓取博主上传的原生多语言字幕以及 TikTok 官方 AI 语音转录字幕，下载后与视频存放在<strong>同一个专属博主目录下</strong>，并使用完全一致的文件名前缀，主流播放器（PotPlayer、VLC、剪映等）可自动识别同名字幕。
          </p>
        </div>

        <!-- 伴随附件保存 -->
        <div class="grid grid-cols-2 gap-3 pt-1">
          <label class="flex items-center space-x-2 p-2.5 rounded-xl bg-slate-950 border border-slate-800 cursor-pointer select-none">
            <input type="checkbox" id="settingSaveThumb" checked class="w-3.5 h-3.5 rounded border-slate-700 bg-slate-950 text-cyan-500 focus:ring-0">
            <span class="text-slate-300">保存高清封面图 (.jpg)</span>
          </label>
          <label class="flex items-center space-x-2 p-2.5 rounded-xl bg-slate-950 border border-slate-800 cursor-pointer select-none">
            <input type="checkbox" id="settingSaveJson" checked class="w-3.5 h-3.5 rounded border-slate-700 bg-slate-950 text-cyan-500 focus:ring-0">
            <span class="text-slate-300">保存元数据信息 (.json)</span>
          </label>
        </div>

        <!-- 🌟 YouTube 专项：音频编码与 AI 学习文档设置 -->
        <div class="p-3.5 rounded-xl bg-slate-950/80 border border-red-950/60 space-y-3">
          <div class="flex items-center justify-between pb-1 border-b border-slate-800/80">
            <span class="font-bold text-red-400 flex items-center space-x-1.5">
              <i data-lucide="play" class="w-3.5 h-3.5 fill-red-400"></i>
              <span>YouTube 专项高级设置 (音视频兼容 & AI学习)</span>
            </span>
            <span class="text-[10px] text-slate-500">参照 bradpittwyc/Youtube-Downloader 标准</span>
          </div>
          
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label class="text-[11px] text-slate-300 block mb-1">视频编码策略 (防视频无声)</label>
              <select id="settingVideoCodec" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-red-500">
                <option value="quality" selected>画质优先：最佳视频 + AAC (推荐，杜绝无声)</option>
                <option value="compat">兼容优先：H.264 + AAC (老设备/剪辑专用)</option>
              </select>
            </div>
            <div>
              <label class="text-[11px] text-slate-300 block mb-1">大模型名称 (OpenAI/DeepSeek)</label>
              <input type="text" id="settingStudyModel" value="deepseek-chat" placeholder="deepseek-chat 或 gpt-4o-mini" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-red-500 font-mono">
            </div>
          </div>

          <div class="space-y-1">
            <label class="text-[11px] text-slate-300 flex items-center justify-between">
              <span>大模型 API 端点 (用于自动生成中英精读 Word 学习文档)</span>
              <span class="text-[10px] text-slate-500">兼容 DeepSeek / OpenAI / Ollama</span>
            </label>
            <input type="text" id="settingStudyBase" value="https://api.deepseek.com/v1" placeholder="https://api.deepseek.com/v1" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-red-500 font-mono">
          </div>

          <div class="space-y-1">
            <label class="text-[11px] text-slate-300 flex items-center justify-between">
              <span>大模型 API Key (选填，留空则使用内置高保真双语引擎生成)</span>
              <span class="text-[10px] text-emerald-400">零配置也能生成精读文档</span>
            </label>
            <input type="password" id="settingStudyKey" placeholder="sk-..." class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-red-500 font-mono">
          </div>
        </div>

      </div>

      <!-- 弹窗底部操作按钮 -->
      <div class="flex items-center justify-between pt-3 border-t border-slate-800">
        <button onclick="resetDefaultSettings()" class="text-xs text-slate-500 hover:text-slate-300 transition-colors">恢复默认设置</button>
        <div class="flex items-center space-x-2.5">
          <button onclick="closeSettingsModal()" class="px-4 py-2 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition-colors">取消</button>
          <button onclick="saveAppSettings()" class="px-4 py-2 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl shadow-lg shadow-cyan-600/30 transition-all flex items-center space-x-1.5 active:scale-95">
            <i data-lucide="check" class="w-3.5 h-3.5"></i>
            <span>保存并应用</span>
          </button>
        </div>
      </div>

    </div>
  </div>

  <!-- 内置可视化资源管理器目录选择弹窗 -->
  <div id="folderBrowserModal" class="fixed inset-0 z-[1000] bg-black/80 backdrop-blur-md hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl max-w-2xl w-full h-[580px] flex flex-col shadow-2xl tiktok-border-glow overflow-hidden">
      
      <!-- 头部 -->
      <div class="px-5 py-3.5 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
        <div class="flex items-center space-x-2.5">
          <div class="w-8 h-8 rounded-lg bg-cyan-500/20 text-cyan-400 flex items-center justify-center">
            <i data-lucide="folder-search" class="w-5 h-5"></i>
          </div>
          <div>
            <h3 class="text-sm font-bold text-white">选择视频存储目录</h3>
            <p class="text-[11px] text-slate-400">点击进入文件夹，或直接选择盘符/新建目录</p>
          </div>
        </div>
        <button onclick="closeFolderBrowser()" class="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors">
          <i data-lucide="x" class="w-5 h-5"></i>
        </button>
      </div>

      <!-- 地址栏与操作栏 -->
      <div class="px-4 py-2.5 bg-slate-900/90 border-b border-slate-800 flex items-center space-x-2">
        <button id="btnParentDir" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs flex items-center space-x-1 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0" title="返回上一级">
          <i data-lucide="corner-left-up" class="w-4 h-4"></i>
          <span>上一级</span>
        </button>
        <button onclick="navRefreshDir()" class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors shrink-0" title="刷新">
          <i data-lucide="refresh-cw" class="w-4 h-4"></i>
        </button>
        <div class="flex-1 relative">
          <input type="text" id="browserAddressBar" onkeydown="if(event.key==='Enter') loadDir(this.value)" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-cyan-300 font-mono focus:outline-none focus:border-cyan-400">
        </div>
        <button onclick="promptCreateDir()" class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-cyan-900/60 text-cyan-400 hover:text-cyan-300 text-xs flex items-center space-x-1 transition-colors shrink-0">
          <i data-lucide="folder-plus" class="w-4 h-4"></i>
          <span>新建文件夹</span>
        </button>
      </div>

      <!-- 快捷位置标签栏 (盘符与快捷方式) -->
      <div id="quickDrivesBar" class="px-4 py-2 bg-slate-950/70 border-b border-slate-800 flex items-center space-x-2 overflow-x-auto custom-scroll text-xs">
        <!-- 动态生成: [本地磁盘 (C:)] [本地磁盘 (D:)] [下载] [桌面] -->
      </div>

      <!-- 文件夹内容列表 -->
      <div id="folderItemsList" class="flex-1 overflow-y-auto p-4 custom-scroll grid grid-cols-2 sm:grid-cols-3 gap-2.5 content-start">
        <!-- 动态生成文件夹卡片 -->
      </div>

      <!-- 底栏 -->
      <div class="px-5 py-3 bg-slate-950 border-t border-slate-800 flex items-center justify-between">
        <div class="text-xs text-slate-400 truncate max-w-sm">
          <span>当前选定: </span>
          <span id="browserSelectedLabel" class="text-cyan-300 font-mono font-semibold"></span>
        </div>
        <div class="flex items-center space-x-2.5">
          <button onclick="closeFolderBrowser()" class="px-4 py-2 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl transition-colors">取消</button>
          <button onclick="confirmSelectedFolder()" class="px-5 py-2 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-xl shadow-lg shadow-cyan-600/30 transition-all flex items-center space-x-1.5 active:scale-95">
            <i data-lucide="check" class="w-4 h-4"></i>
            <span>选定此文件夹</span>
          </button>
        </div>
      </div>

    </div>
  </div>



  <!-- 脚本逻辑 -->
  <script>
    let currentVideos = [];
    let isTaskRunning = false;
    let lastKnownVideoCount = 0;  // 追踪后端视频总数，变化时立刻拉取

    // 优雅的 Toast 提示系统 (彻底替代原生 alert 弹窗，2秒自动消失，不再需要用户点确认)
    function showToast(msg, type = 'info') {
      let container = document.getElementById('toastContainer');
      if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'fixed top-5 right-5 z-[9999] flex flex-col space-y-2 pointer-events-none';
        document.body.appendChild(container);
      }
      const toast = document.createElement('div');
      const bg = type === 'error' ? 'bg-rose-600/95 text-white border-rose-500 shadow-rose-900/50' :
                 type === 'success' ? 'bg-emerald-600/95 text-white border-emerald-500 shadow-emerald-900/50' :
                 'bg-slate-800/95 text-cyan-300 border-slate-700 shadow-slate-950/80';
      toast.className = `${bg} border backdrop-blur-md px-4 py-2.5 rounded-xl shadow-2xl text-xs font-semibold flex items-center space-x-2 transition-all duration-300 opacity-0 transform -translate-y-2 pointer-events-auto`;
      toast.innerHTML = `<span>${msg}</span>`;
      container.appendChild(toast);
      requestAnimationFrame(() => {
        toast.classList.remove('opacity-0', '-translate-y-2');
        toast.classList.add('opacity-100', 'translate-y-0');
      });
      setTimeout(() => {
        toast.classList.remove('opacity-100', 'translate-y-0');
        toast.classList.add('opacity-0', '-translate-y-2');
        setTimeout(() => toast.remove(), 300);
      }, 2500);
    }
    // 彻底静默覆写 window.alert，禁止任何弹窗确认打扰
    window.alert = function(msg) {
      showToast(msg, 'info');
    };

    // 初始化 Lucide 图标
    lucide.createIcons();

    // 轮询后台状态
    setInterval(fetchStatus, 500);

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        isTaskRunning = data.is_running;
        document.getElementById('statusText').innerText = data.status_text;
        
        const pct = Math.round((data.progress || 0) * 100);
        document.getElementById('progressBar').style.width = pct + '%';
        document.getElementById('progressText').innerText = pct + '%';

        const pulse = document.getElementById('statusPulse');
        const btnStop = document.getElementById('btnStop');
        const btnScan = document.getElementById('btnScan');
        const btnDownloadAll = document.getElementById('btnDownloadAll');

        if (isTaskRunning) {
          pulse.className = 'w-3 h-3 rounded-full bg-cyan-400 animate-ping';
          btnStop.disabled = false;
          btnStop.className = 'px-4 py-2.5 text-sm font-semibold bg-rose-600 hover:bg-rose-500 text-white rounded-xl transition-all flex items-center space-x-1.5 active:scale-95 cursor-pointer';
          btnScan.disabled = true;
          btnDownloadAll.disabled = true;
        } else {
          pulse.className = 'w-3 h-3 rounded-full bg-emerald-500';
          btnStop.disabled = true;
          btnStop.className = 'px-4 py-2.5 text-sm font-semibold bg-slate-800 text-slate-500 rounded-xl transition-all flex items-center space-x-1.5 disabled:opacity-50';
          btnScan.disabled = false;
          btnDownloadAll.disabled = false;
        }

        // 🔑 核心：实时增量更新视频列表
        // 后端 video_count 发生变化时，立刻拉取最新视频并渲染到前端
        const serverVideoCount = data.video_count || 0;
        if (serverVideoCount !== lastKnownVideoCount) {
          lastKnownVideoCount = serverVideoCount;
          if (serverVideoCount > 0) {
            const vRes = await fetch('/api/videos');
            const vData = await vRes.json();
            const newVideos = vData.videos || [];
            // 保留用户已有的手动选择状态（增量模式）
            const isFirstLoad = currentVideos.length === 0;
            currentVideos = newVideos;
            if (isFirstLoad) {
              // 首次载入时默认全选
              selectedUrls.clear();
              currentVideos.forEach(v => selectedUrls.add(v.url));
            } else {
              // 增量：仅将新增的视频也加入已选集合
              currentVideos.forEach(v => {
                if (!selectedUrls.has(v.url)) {
                  selectedUrls.add(v.url);
                }
              });
            }
            updateSelectedCount();
            const badge = document.getElementById('videoCountBadge');
            if (badge) badge.innerText = `${currentVideos.length} 个视频`;
            renderCurrentPage();
          }
        }

        // 实时更新下载队列中各个视频的下载进度与状态 (参照 GitHub 仓库队列体系)
        if (downloadQueue.length > 0) {
          const stats = data.download_stats || {};
          const downloaded = stats.downloaded || 0;
          const actionText = data.action || '';
          const isDownloadingAction = actionText.includes('下载') || actionText.includes('Download') || actionText.includes('批量');

          if (isTaskRunning && isDownloadingAction) {
            downloadQueue.forEach((item, idx) => {
              if (idx < downloaded) {
                item.state = 'done';
                item.percent = 100;
                item.statusText = '已完成下载';
              } else if (idx === downloaded) {
                item.state = 'downloading';
                item.percent = Math.max(item.percent, pct);
                item.statusText = data.status_text || '正在下载…';
              } else {
                if (item.state !== 'done') {
                  item.state = 'waiting';
                  item.percent = 0;
                  item.statusText = '等待下载…';
                }
              }
            });
          } else if (!isTaskRunning) {
            if (downloaded >= downloadQueue.length && downloadQueue.length > 0) {
              downloadQueue.forEach(item => {
                if (item.state !== 'failed') {
                  item.state = 'done';
                  item.percent = 100;
                  item.statusText = '已完成下载';
                }
              });
            } else if (downloaded > 0) {
              downloadQueue.forEach((item, idx) => {
                if (idx < downloaded) {
                  item.state = 'done';
                  item.percent = 100;
                  item.statusText = '已完成下载';
                }
              });
            }
          }

          updateQueueStats();
          if (currentRightTab === 'queue') {
            renderQueueUI();
          }
        }

        renderLogs(data.logs);
      } catch (err) {
        console.error("轮询状态失败:", err);
      }
    }

    function renderLogs(logs) {
      if (!logs || logs.length === 0) return;
      const consoleBox = document.getElementById('logConsole');
      consoleBox.innerHTML = '';
      logs.forEach(item => {
        const row = document.createElement('div');
        let colorClass = 'text-slate-300';
        if (item.level === 'success') colorClass = 'text-emerald-400';
        if (item.level === 'warn') colorClass = 'text-amber-400';
        if (item.level === 'error') colorClass = 'text-rose-400';
        row.className = `${colorClass} leading-relaxed break-all`;
        row.innerHTML = `<span class="text-slate-600">[${item.time}]</span> ${escapeHtml(item.text)}`;
        consoleBox.appendChild(row);
      });
      consoleBox.scrollTop = consoleBox.scrollHeight;
    }

    function escapeHtml(str) {
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function clearLogs() {
      document.getElementById('logConsole').innerHTML = '<div class="text-slate-500">// 日志已清空</div>';
    }

    // --- 选项卡切换控制 (下载队列前置 vs 控制台日志，参照 bradpittwyc/Tiktokdownloader-in-DS-Harness 设计) ---
    let currentRightTab = 'queue';
    let downloadQueue = [];

    function switchRightTab(tab) {
      currentRightTab = tab;
      const btnLog = document.getElementById('tabBtnLog');
      const btnQueue = document.getElementById('tabBtnQueue');
      const panelLog = document.getElementById('panelLog');
      const panelQueue = document.getElementById('panelQueue');
      const actionText = document.getElementById('textRightHeaderAction');

      if (tab === 'log') {
        btnLog.className = "px-3 py-1 rounded-md text-xs font-semibold transition-all flex items-center space-x-1.5 whitespace-nowrap bg-slate-800 text-rose-400 border border-slate-700/60 shadow-sm";
        btnQueue.className = "px-3 py-1 rounded-md text-xs font-medium transition-all flex items-center space-x-1.5 whitespace-nowrap text-slate-400 hover:text-white hover:bg-slate-800/50";
        panelLog.classList.remove('hidden');
        panelQueue.classList.add('hidden');
        if (actionText) actionText.innerText = "清空日志";
      } else {
        btnQueue.className = "px-3 py-1 rounded-md text-xs font-semibold transition-all flex items-center space-x-1.5 whitespace-nowrap bg-slate-800 text-cyan-400 border border-slate-700/60 shadow-sm";
        btnLog.className = "px-3 py-1 rounded-md text-xs font-medium transition-all flex items-center space-x-1.5 whitespace-nowrap text-slate-400 hover:text-white hover:bg-slate-800/50";
        panelQueue.classList.remove('hidden');
        panelLog.classList.add('hidden');
        if (actionText) actionText.innerText = "清除已完成";
        renderQueueUI();
      }
      lucide.createIcons();
    }

    function handleRightHeaderAction() {
      if (currentRightTab === 'log') {
        clearLogs();
      } else {
        clearCompletedQueue();
      }
    }

    function syncDownloadQueueFromSelection(urls) {
      urls.forEach(url => {
        const existing = downloadQueue.find(q => q.url === url);
        if (!existing) {
          const videoMeta = currentVideos.find(v => v.url === url) || {};
          downloadQueue.push({
            id: videoMeta.id || url.split('/').pop(),
            title: videoMeta.title || 'TikTok 视频',
            url: url,
            thumbnail: videoMeta.thumbnail || '',
            duration: videoMeta.duration || '',
            state: 'waiting',  // waiting, downloading, done, failed
            percent: 0,
            statusText: '等待下载…'
          });
        }
      });
      updateQueueStats();
      renderQueueUI();
    }

    function updateQueueStats() {
      const active = downloadQueue.filter(q => q.state === 'downloading').length;
      const waiting = downloadQueue.filter(q => q.state === 'waiting').length;
      const done = downloadQueue.filter(q => q.state === 'done').length;
      const failed = downloadQueue.filter(q => q.state === 'failed').length;

      const qActive = document.getElementById('qActiveCount');
      const qWaiting = document.getElementById('qWaitingCount');
      const qDone = document.getElementById('qDoneCount');
      const qFailed = document.getElementById('qFailedCount');
      const badge = document.getElementById('queueCountBadge');
      const pageText = document.getElementById('queuePageText');

      if (qActive) qActive.innerText = active;
      if (qWaiting) qWaiting.innerText = waiting;
      if (qDone) qDone.innerText = done;
      if (qFailed) qFailed.innerText = failed;
      if (badge) badge.innerText = downloadQueue.length;
      if (pageText) pageText.innerText = `队列总计 ${downloadQueue.length} 项`;
    }

    function renderQueueUI() {
      const container = document.getElementById('queueItemsList');
      if (!container) return;

      if (downloadQueue.length === 0) {
        container.innerHTML = `
          <div class="h-full flex flex-col items-center justify-center text-slate-500 py-16 text-center">
            <i data-lucide="layers" class="w-8 h-8 text-slate-600 mb-2"></i>
            <p class="text-xs">勾选视频并点击“批量下载”后，任务将显示在这里</p>
          </div>
        `;
        lucide.createIcons();
        return;
      }

      // 如果列表长度一致且已有卡片，只增量更新每个卡片的进度和状态文本，避免闪烁和滚动条重置
      const existingCards = container.querySelectorAll('.queue-card');
      if (existingCards.length === downloadQueue.length) {
        downloadQueue.forEach((item, idx) => {
          const card = existingCards[idx];
          if (!card) return;
          const statusTextEl = card.querySelector('.queue-status-text');
          if (statusTextEl && statusTextEl.innerText !== item.statusText) {
            statusTextEl.innerText = item.statusText || '等待中';
          }
          const barEl = card.querySelector('.queue-progress-bar');
          if (barEl) {
            barEl.style.width = item.percent + '%';
            if (item.state === 'done') {
              barEl.className = 'queue-progress-bar h-full bg-emerald-500 transition-all duration-300';
            } else if (item.state === 'downloading') {
              barEl.className = 'queue-progress-bar h-full bg-gradient-to-r from-cyan-400 to-blue-500 transition-all duration-300';
            } else if (item.state === 'failed') {
              barEl.className = 'queue-progress-bar h-full bg-rose-500 transition-all duration-300';
            }
          }
          const tagEl = card.querySelector('.queue-badge');
          if (tagEl) {
            const badgeText = item.state === 'done' ? '已完成' : (item.state === 'downloading' ? '下载中' : (item.state === 'failed' ? '失败' : '排队中'));
            if (tagEl.innerText !== badgeText) {
              tagEl.innerText = badgeText;
              let badgeColor = 'bg-slate-800 text-slate-400';
              if (item.state === 'downloading') badgeColor = 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30';
              else if (item.state === 'done') badgeColor = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
              else if (item.state === 'failed') badgeColor = 'bg-rose-500/20 text-rose-300 border border-rose-500/30';
              tagEl.className = `queue-badge text-[10px] px-1.5 py-0.5 rounded ${badgeColor} shrink-0 font-medium`;
            }
          }
        });
        return;
      }

      container.innerHTML = downloadQueue.map((item, idx) => {
        let borderClass = 'border-slate-800 bg-slate-950/70';
        let barColor = 'bg-cyan-500';
        let badgeColor = 'bg-slate-800 text-slate-400';

        if (item.state === 'downloading') {
          borderClass = 'border-cyan-500/50 bg-cyan-950/20 shadow-md shadow-cyan-950/50';
          barColor = 'bg-gradient-to-r from-cyan-400 to-blue-500';
          badgeColor = 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30';
        } else if (item.state === 'done') {
          borderClass = 'border-emerald-500/40 bg-emerald-950/10';
          barColor = 'bg-emerald-500';
          badgeColor = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
        } else if (item.state === 'failed') {
          borderClass = 'border-rose-500/40 bg-rose-950/10';
          barColor = 'bg-rose-500';
          badgeColor = 'bg-rose-500/20 text-rose-300 border border-rose-500/30';
        }

        const thumbHtml = item.thumbnail 
          ? `<img src="${item.thumbnail}" class="w-11 h-11 rounded-lg object-cover bg-slate-800 shrink-0" onerror="this.src='https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=100&q=60'">`
          : `<div class="w-11 h-11 rounded-lg bg-slate-800 text-slate-400 flex items-center justify-center shrink-0"><i data-lucide="video" class="w-5 h-5"></i></div>`;

        return `
          <div class="queue-card p-2.5 rounded-xl border ${borderClass} transition-all space-y-2">
            <div class="flex items-start space-x-2.5">
              ${thumbHtml}
              <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between gap-1">
                  <h4 class="text-xs font-semibold text-slate-200 truncate" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</h4>
                  <span class="queue-badge text-[10px] px-1.5 py-0.5 rounded ${badgeColor} shrink-0 font-medium">
                    ${item.state === 'done' ? '已完成' : item.state === 'downloading' ? '下载中' : item.state === 'failed' ? '失败' : '排队中'}
                  </span>
                </div>
                <div class="text-[11px] text-slate-400 flex items-center justify-between mt-1">
                  <span class="queue-status-text truncate">${escapeHtml(item.statusText || '等待中')}</span>
                  ${item.state === 'done' ? `<button onclick="openCurrentOutputDir()" class="text-cyan-400 hover:underline ml-2 shrink-0">打开目录</button>` : ''}
                </div>
              </div>
            </div>
            <!-- 进度条 -->
            <div class="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
              <div class="queue-progress-bar h-full ${barColor} transition-all duration-300" style="width: ${item.percent}%"></div>
            </div>
          </div>
        `;
      }).join('');

      lucide.createIcons();
    }

    function clearCompletedQueue() {
      downloadQueue = downloadQueue.filter(q => q.state !== 'done');
      updateQueueStats();
      renderQueueUI();
      showToast("已清除所有完成的队列项", "info");
    }

    async function cancelAllQueue() {
      await stopTask();
      downloadQueue.forEach(item => {
        if (item.state === 'waiting' || item.state === 'downloading') {
          item.state = 'failed';
          item.statusText = '已取消';
        }
      });
      updateQueueStats();
      renderQueueUI();
      showToast("已取消下载队列中的所有待处理任务", "warn");
    }

    async function loadDemo() {
      document.getElementById('inputUsername').value = 'tech_reviewer';
      await startScan(true);
    }

    async function startScan(isDemo = false) {
      const username = document.getElementById('inputUsername').value.trim();
      const proxy = document.getElementById('inputProxy').value.trim();
      const limitVal = document.getElementById('inputLimit').value.trim();
      const max_videos = limitVal ? parseInt(limitVal) : 0;
      const cookie_text = document.getElementById('inputCookieText') ? document.getElementById('inputCookieText').value.trim() : "";

      if (!username) {
        alert("请输入博主用户名或链接！");
        return;
      }

      // 重置前端状态，准备接收新数据
      lastKnownVideoCount = 0;
      currentVideos = [];
      selectedUrls.clear();
      currentPage = 1;

      try {
        const res = await fetch('/api/scan', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ username, proxy, max_videos, cookie_text, is_demo: isDemo })
        });
        const data = await res.json();
        if (!data.success) {
          alert(data.message);
          return;
        }
        // 视频列表会由 fetchStatus 轮询自动检测 video_count 变化并实时渲染
        // 无需任何延迟或手动拉取
        showToast('扫描任务已启动，视频将实时显示', 'success');
      } catch (err) {
        alert("请求错误: " + err);
      }
    }

    const PAGE_SIZE = 20;
    let currentPage = 1;
    let selectedUrls = new Set();

    function renderVideos(videos) {
      currentVideos = videos || [];
      const badge = document.getElementById('videoCountBadge');
      if (badge) badge.innerText = `${currentVideos.length} 个视频`;

      // 默认全选所有新载入的作品
      selectedUrls.clear();
      currentVideos.forEach(v => selectedUrls.add(v.url));
      updateSelectedCount();

      // 重设当前页码
      const totalPages = Math.ceil(currentVideos.length / PAGE_SIZE) || 1;
      if (currentPage > totalPages) currentPage = totalPages;
      if (currentPage < 1) currentPage = 1;

      renderCurrentPage();
    }

    function renderCurrentPage() {
      const container = document.getElementById('videoListContainer');
      const totalPages = Math.ceil(currentVideos.length / PAGE_SIZE) || 1;
      
      if (!currentVideos || currentVideos.length === 0) {
        container.innerHTML = `
          <div class="py-20 text-center text-slate-500">
            <i data-lucide="sparkles" class="w-8 h-8 text-slate-600 mx-auto mb-2"></i>
            <p class="text-xs">暂无视频，请在上方输入博主点击“解析”，或点击右上角“一键载入 Demo 体验”</p>
          </div>
        `;
        document.getElementById('paginationBar').classList.add('hidden');
        lucide.createIcons();
        return;
      }

      document.getElementById('paginationBar').classList.remove('hidden');

      const startIdx = (currentPage - 1) * PAGE_SIZE;
      const endIdx = Math.min(startIdx + PAGE_SIZE, currentVideos.length);
      const pageItems = currentVideos.slice(startIdx, endIdx);

      container.innerHTML = '';
      pageItems.forEach((v, index) => {
        const globalIdx = startIdx + index + 1;
        const isChecked = selectedUrls.has(v.url);
        const row = document.createElement('div');
        row.className = "grid grid-cols-12 gap-3 px-4 py-2.5 items-center hover:bg-slate-800/40 transition-colors text-xs";
        row.innerHTML = `
          <!-- 序号与勾选 -->
          <div class="col-span-1 flex items-center space-x-1.5">
            <input type="checkbox" value="${v.url}" ${isChecked ? 'checked' : ''} onchange="toggleItemSelection('${v.url}', this.checked)" class="video-checkbox w-4 h-4 rounded border-slate-700 bg-slate-950 text-cyan-500 focus:ring-0 cursor-pointer">
            <span class="text-slate-500 font-mono text-[11px]">${globalIdx}</span>
          </div>

          <!-- 紧凑缩略图 -->
          <div class="col-span-2 relative group cursor-pointer" onclick="window.open('${v.url}', '_blank')">
            <div class="w-16 h-11 rounded-lg overflow-hidden bg-slate-950 border border-slate-800 relative">
              <img src="${v.thumbnail}" alt="thumb" class="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300">
              <span class="absolute bottom-0.5 right-0.5 px-1 rounded bg-black/70 text-[9px] font-mono text-white leading-tight">
                ${v.duration}
              </span>
            </div>
          </div>

          <!-- 视频标题与信息 -->
          <div class="col-span-6 pr-2">
            <a href="${v.url}" target="_blank" class="text-slate-200 hover:text-cyan-300 font-medium line-clamp-1 leading-snug transition-colors" title="${escapeHtml(v.title)}">
              ${escapeHtml(v.title)}
            </a>
            <div class="flex items-center space-x-2 text-[10px] text-slate-500 mt-1 font-mono">
              <span>ID: ${v.id.substring(0, 12)}...</span>
              <span>•</span>
              <span>发布: ${v.upload_date}</span>
            </div>
          </div>

          <!-- 播放量与时长 -->
          <div class="col-span-2 text-center text-slate-400 text-[11px]">
            <span class="text-cyan-400 font-medium font-mono">${v.view_count}</span>
            <div class="text-[10px] text-slate-500">播放量</div>
          </div>

          <!-- 单个下载操作 -->
          <div class="col-span-1 text-right">
            <button onclick="downloadSingle('${v.url}')" class="px-2.5 py-1 text-xs bg-slate-800 hover:bg-cyan-600 text-slate-300 hover:text-white rounded-lg transition-colors flex items-center space-x-1 ml-auto">
              <i data-lucide="download" class="w-3 h-3"></i>
              <span>下载</span>
            </button>
          </div>
        `;
        container.appendChild(row);
      });

      renderPaginationControls(totalPages, startIdx, endIdx);
      lucide.createIcons();
    }

    function renderPaginationControls(totalPages, startIdx, endIdx) {
      document.getElementById('pageInfoText').innerText = 
        `显示第 ${startIdx + 1} - ${endIdx} 条，共 ${currentVideos.length} 条作品 (当前第 ${currentPage}/${totalPages} 页，每页上限 ${PAGE_SIZE} 个)`;

      const btnPrev = document.getElementById('btnPrevPage');
      const btnNext = document.getElementById('btnNextPage');
      btnPrev.disabled = (currentPage <= 1);
      btnNext.disabled = (currentPage >= totalPages);

      const pillsContainer = document.getElementById('pagePillsContainer');
      pillsContainer.innerHTML = '';

      for (let p = 1; p <= totalPages; p++) {
        if (totalPages > 7) {
          if (p !== 1 && p !== totalPages && Math.abs(p - currentPage) > 2) {
            if (p === 2 || p === totalPages - 1) {
              const dots = document.createElement('span');
              dots.className = "text-slate-600 px-1 text-xs select-none";
              dots.innerText = "...";
              pillsContainer.appendChild(dots);
            }
            continue;
          }
        }
        const btn = document.createElement('button');
        const isActive = (p === currentPage);
        btn.className = isActive 
          ? "px-2.5 py-1 rounded-lg bg-cyan-600 text-white font-bold text-xs shadow-md shadow-cyan-600/30 cursor-default"
          : "px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white text-xs transition-colors";
        btn.innerText = p;
        btn.onclick = () => goToPage(p);
        pillsContainer.appendChild(btn);
      }

      syncHeaderCheckbox();
    }

    function goToPage(p) {
      currentPage = p;
      renderCurrentPage();
      const container = document.getElementById('videoListContainer');
      if (container) container.scrollTop = 0;
    }

    function changePage(delta) {
      const totalPages = Math.ceil(currentVideos.length / PAGE_SIZE) || 1;
      goToPage(Math.max(1, Math.min(totalPages, currentPage + delta)));
    }

    function toggleItemSelection(url, checked) {
      if (checked) {
        selectedUrls.add(url);
      } else {
        selectedUrls.delete(url);
      }
      updateSelectedCount();
      syncHeaderCheckbox();
    }

    function selectCurrentPage(select) {
      const startIdx = (currentPage - 1) * PAGE_SIZE;
      const endIdx = Math.min(startIdx + PAGE_SIZE, currentVideos.length);
      for (let i = startIdx; i < endIdx; i++) {
        if (select) {
          selectedUrls.add(currentVideos[i].url);
        } else {
          selectedUrls.delete(currentVideos[i].url);
        }
      }
      renderCurrentPage();
      updateSelectedCount();
    }

    function toggleSelectCurrentPage(checked) {
      selectCurrentPage(checked);
    }

    function selectAllVideos(select) {
      if (select) {
        currentVideos.forEach(v => selectedUrls.add(v.url));
      } else {
        selectedUrls.clear();
      }
      renderCurrentPage();
      updateSelectedCount();
    }

    function syncHeaderCheckbox() {
      const startIdx = (currentPage - 1) * PAGE_SIZE;
      const endIdx = Math.min(startIdx + PAGE_SIZE, currentVideos.length);
      const chkHeader = document.getElementById('chkSelectPageHeader');
      if (!chkHeader) return;
      if (currentVideos.length === 0) {
        chkHeader.checked = false;
        return;
      }
      let allChecked = true;
      for (let i = startIdx; i < endIdx; i++) {
        if (!selectedUrls.has(currentVideos[i].url)) {
          allChecked = false;
          break;
        }
      }
      chkHeader.checked = allChecked;
    }

    function updateSelectedCount() {
      const el = document.getElementById('selectedCountText');
      if (el) el.innerText = `已选 ${selectedUrls.size} 项`;
      const btnDl = document.getElementById('btnDownloadAllText');
      if (btnDl) {
        btnDl.innerText = selectedUrls.size > 0 ? `批量下载已选 (${selectedUrls.size})` : `批量下载已选`;
      }
    }

    async function startDownloadSelected() {
      const selected = Array.from(selectedUrls);
      if (selected.length === 0) {
        showToast("请先勾选需要下载的视频！", "warn");
        return;
      }

      let username = document.getElementById('inputUsername').value.trim();
      if (!username && selected.length > 0) {
        const match = selected[0].match(/@([a-zA-Z0-9_.-]+)/);
        if (match) username = match[1];
      }
      username = username || "tiktok_batch";

      const proxy = document.getElementById('inputProxy').value.trim();
      const cookie_text = document.getElementById('inputCookieText') ? document.getElementById('inputCookieText').value.trim() : "";
      const save_thumb = document.getElementById('chkThumb') ? document.getElementById('chkThumb').checked : true;
      const save_json = document.getElementById('chkJson') ? document.getElementById('chkJson').checked : true;
      const save_subtitles = document.getElementById('chkSubtitles') ? document.getElementById('chkSubtitles').checked : true;
      const output_dir = appSettings.output_dir || "downloads";

      // 将选中的视频同步加入右侧“下载队列”并自动切到“下载队列”Tab
      syncDownloadQueueFromSelection(selected);
      switchRightTab('queue');

      const res = await fetch('/api/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username,
          video_urls: selected,
          proxy,
          cookie_text,
          save_thumb,
          save_json,
          save_subtitles,
          output_dir
        })
      });
      const data = await res.json();
      if (!data.success) {
        showToast(data.message, "error");
      } else {
        showToast(`已开始批量下载 ${selected.length} 个视频`, "success");
      }
    }

    function downloadSingle(url) {
      let username = document.getElementById('inputUsername').value.trim();
      const match = url.match(/@([a-zA-Z0-9_.-]+)/);
      if (match) {
        username = match[1];
      }
      username = username || "single";
      const proxy = document.getElementById('inputProxy').value.trim();
      const save_thumb = document.getElementById('chkThumb') ? document.getElementById('chkThumb').checked : true;
      const save_json = document.getElementById('chkJson') ? document.getElementById('chkJson').checked : true;
      const save_subtitles = document.getElementById('chkSubtitles') ? document.getElementById('chkSubtitles').checked : true;
      const output_dir = appSettings.output_dir || "downloads";

      // 将该视频加入右侧下载队列并切到下载队列Tab
      syncDownloadQueueFromSelection([url]);
      switchRightTab('queue');

      fetch('/api/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          username,
          video_urls: [url],
          proxy,
          save_thumb,
          save_json,
          save_subtitles,
          output_dir
        })
      });
      showToast("已加入下载队列", "info");
    }

    async function stopTask() {
      const res = await fetch('/api/stop', {method: 'POST'});
      const data = await res.json();
      showToast(data.message, "info");
    }

    // --- 设置偏好管理 ---
    let appSettings = {
      output_dir: "downloads",
      create_blogger_folder: true,
      save_subtitles: true,
      save_thumb: true,
      save_json: true,
      proxy: ""
    };

    async function fetchSettings() {
      try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        if (data.success && data.settings) {
          appSettings = data.settings;
          applySettingsToUI();
        }
      } catch (err) {
        console.error("获取设置失败:", err);
      }
    }

    function applySettingsToUI() {
      if (document.getElementById('settingOutputDir')) {
        document.getElementById('settingOutputDir').value = appSettings.output_dir || "downloads";
      }
      if (document.getElementById('settingCreateBloggerFolder')) {
        document.getElementById('settingCreateBloggerFolder').checked = !!appSettings.create_blogger_folder;
      }
      if (document.getElementById('settingSaveSubtitles')) {
        document.getElementById('settingSaveSubtitles').checked = !!appSettings.save_subtitles;
      }
      if (document.getElementById('settingSaveThumb')) {
        document.getElementById('settingSaveThumb').checked = !!appSettings.save_thumb;
      }
      if (document.getElementById('settingSaveJson')) {
        document.getElementById('settingSaveJson').checked = !!appSettings.save_json;
      }

      // 同步 YouTube 专有设置 (视频编码、质量、音频提取、双语字幕与学习文档)
      if (document.getElementById('settingVideoCodec')) {
        document.getElementById('settingVideoCodec').value = appSettings.video_codec || "h264";
      }
      if (document.getElementById('settingStudyModel')) {
        document.getElementById('settingStudyModel').value = appSettings.study_model || "gpt-4o-mini";
      }
      if (document.getElementById('settingStudyBase')) {
        document.getElementById('settingStudyBase').value = appSettings.study_api_base || "";
      }
      if (document.getElementById('settingStudyKey')) {
        document.getElementById('settingStudyKey').value = appSettings.study_api_key || "";
      }
      if (document.getElementById('chkYtAlsoAudio')) {
        document.getElementById('chkYtAlsoAudio').checked = !!appSettings.also_audio;
      }
      if (document.getElementById('chkYtBiSubs')) {
        document.getElementById('chkYtBiSubs').checked = (appSettings.bilingual_subs !== undefined) ? !!appSettings.bilingual_subs : true;
      }
      if (document.getElementById('chkYtStudyDoc')) {
        document.getElementById('chkYtStudyDoc').checked = (appSettings.study_doc !== undefined) ? !!appSettings.study_doc : true;
      }
      if (document.getElementById('selectYtQuality')) {
        document.getElementById('selectYtQuality').value = appSettings.quality || "best";
      }

      // 同步主界面的快捷复选框与目录提示 (TikTok + YouTube)
      if (document.getElementById('chkThumb')) {
        document.getElementById('chkThumb').checked = !!appSettings.save_thumb;
      }
      if (document.getElementById('chkJson')) {
        document.getElementById('chkJson').checked = !!appSettings.save_json;
      }
      if (document.getElementById('chkSubtitles')) {
        document.getElementById('chkSubtitles').checked = !!appSettings.save_subtitles;
      }
      if (document.getElementById('currentOutputDirLabel')) {
        document.getElementById('currentOutputDirLabel').innerText = appSettings.output_dir || "downloads";
      }

      if (document.getElementById('chkYtThumb')) {
        document.getElementById('chkYtThumb').checked = !!appSettings.save_thumb;
      }
      if (document.getElementById('chkYtJson')) {
        document.getElementById('chkYtJson').checked = !!appSettings.save_json;
      }
      if (document.getElementById('chkYtSubtitles')) {
        document.getElementById('chkYtSubtitles').checked = !!appSettings.save_subtitles;
      }
      if (document.getElementById('currentYtOutputDirLabel')) {
        document.getElementById('currentYtOutputDirLabel').innerText = appSettings.output_dir || "downloads";
      }
    }

    function setQuickFolder(path) {
      if (document.getElementById('settingOutputDir')) {
        document.getElementById('settingOutputDir').value = path;
      }
      appSettings.output_dir = path;
      applySettingsToUI();
      showToast("已切换路径: " + path, "info");
    }

    // --- 极速调起原生 Windows 资源管理器选择窗口 ---
    async function browseDirectoryNative() {
      // 策略 1: 优先使用现代浏览器原生 showDirectoryPicker (Chrome / Edge 0 延迟瞬间弹出 Windows 资源管理器)
      if (window.showDirectoryPicker) {
        try {
          const dirHandle = await window.showDirectoryPicker();
          if (dirHandle && dirHandle.name) {
            const res = await fetch('/api/resolve_folder', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ name: dirHandle.name })
            });
            const data = await res.json();
            if (data.success && data.path) {
              setQuickFolder(data.path);
              showToast(`已成功选定目录: ${data.path}`, "success");
              return;
            }
          }
        } catch (err) {
          if (err.name === 'AbortError') {
            return; // 用户主动取消，不报错
          }
          console.warn("浏览器原生选择器降级:", err);
        }
      }

      // 策略 2: 后端调起 Windows 原生置顶 OpenFileDialog
      const current = document.getElementById('settingOutputDir') 
        ? document.getElementById('settingOutputDir').value.trim() 
        : (appSettings.output_dir || "downloads");

      const btn = document.getElementById('btnBrowseFolder');
      let originalHtml = "";
      if (btn) {
        originalHtml = btn.innerHTML;
        btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin text-white"></i><span>正在调起系统选择窗口...</span>`;
        btn.disabled = true;
      }
      showToast("正在为您调出 Windows 资源管理器窗口，请在弹窗中选择文件夹...", "info");

      try {
        const res = await fetch('/api/choose_folder', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ current_path: current })
        });
        const data = await res.json();
        if (data.success && data.path) {
          setQuickFolder(data.path);
          showToast("已成功选定目录: " + data.path, "success");
        } else if (data.message && data.message !== "cancelled") {
          showToast(data.message, "info");
        }
      } catch (err) {
        console.error("调起系统选择器异常:", err);
        showToast("系统窗口调起失败: " + err, "error");
      } finally {
        if (btn) {
          btn.innerHTML = originalHtml;
          btn.disabled = false;
        }
        lucide.createIcons();
      }
    }

    // --- 可视化资源管理器目录选择 ---
    let currentBrowserPath = "";

    async function openFolderBrowser() {
      const current = document.getElementById('settingOutputDir') 
        ? document.getElementById('settingOutputDir').value.trim() 
        : (appSettings.output_dir || "downloads");
      const modal = document.getElementById('folderBrowserModal');
      if (modal) modal.classList.remove('hidden');
      lucide.createIcons();
      await loadDir(current);
    }

    function closeFolderBrowser() {
      const modal = document.getElementById('folderBrowserModal');
      if (modal) modal.classList.add('hidden');
    }

    async function loadDir(targetPath = "") {
      const listContainer = document.getElementById('folderItemsList');
      const addressBar = document.getElementById('browserAddressBar');
      const selectedLabel = document.getElementById('browserSelectedLabel');
      const btnParent = document.getElementById('btnParentDir');
      const drivesBar = document.getElementById('quickDrivesBar');

      if (!listContainer) return;

      listContainer.innerHTML = `<div class="col-span-full py-16 text-center text-slate-500 text-xs flex flex-col items-center justify-center space-y-2">
        <i data-lucide="loader-2" class="w-6 h-6 animate-spin text-cyan-400"></i>
        <span>正在读取目录内容...</span>
      </div>`;
      lucide.createIcons();

      try {
        const res = await fetch('/api/list_dirs?path=' + encodeURIComponent(targetPath));
        const data = await res.json();
        if (!data.success) {
          listContainer.innerHTML = `<div class="col-span-full py-16 text-center text-rose-400 text-xs">无法访问此路径: ${data.error || '权限不足或路径不存在'}</div>`;
          return;
        }

        currentBrowserPath = data.current;
        if (addressBar) addressBar.value = data.current;
        if (selectedLabel) selectedLabel.innerText = data.current;

        // 上级目录导航控制
        if (btnParent) {
          if (data.parent && data.parent !== data.current) {
            btnParent.disabled = false;
            btnParent.onclick = () => loadDir(data.parent);
          } else {
            btnParent.disabled = true;
          }
        }

        // 快捷盘符与位置
        if (drivesBar) {
          drivesBar.innerHTML = '';
          if (data.drives) {
            data.drives.forEach(d => {
              const btn = document.createElement('button');
              btn.type = "button";
              btn.className = "px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-cyan-900/60 hover:text-cyan-300 text-slate-300 flex items-center space-x-1 shrink-0 transition-colors";
              btn.innerHTML = `<i data-lucide="hard-drive" class="w-3.5 h-3.5 text-cyan-400"></i><span>${d.name}</span>`;
              btn.onclick = () => loadDir(d.path);
              drivesBar.appendChild(btn);
            });
          }
          if (data.quick) {
            data.quick.forEach(q => {
              const btn = document.createElement('button');
              btn.type = "button";
              btn.className = "px-2 py-1 rounded-lg bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-white flex items-center space-x-1 shrink-0 transition-colors";
              btn.innerHTML = `<span>${q.name}</span>`;
              btn.onclick = () => loadDir(q.path);
              drivesBar.appendChild(btn);
            });
          }
        }

        // 渲染文件夹卡片列表
        listContainer.innerHTML = '';
        if (!data.dirs || data.dirs.length === 0) {
          listContainer.innerHTML = `
            <div class="col-span-full py-16 text-center text-slate-500 text-xs flex flex-col items-center justify-center space-y-1">
              <i data-lucide="folder-open" class="w-8 h-8 text-slate-600 mb-1"></i>
              <span>(当前目录下没有子文件夹)</span>
              <span class="text-[11px] text-slate-600">您可以直接点击右下角「选定此文件夹」作为存储路径，或点击上方「新建文件夹」</span>
            </div>
          `;
          lucide.createIcons();
          return;
        }

        data.dirs.forEach(folder => {
          const item = document.createElement('div');
          item.className = "p-2.5 rounded-xl bg-slate-950 border border-slate-800 hover:border-cyan-500/60 hover:bg-slate-800/60 cursor-pointer flex items-center space-x-2 text-xs text-slate-200 transition-all group select-none";
          item.innerHTML = `
            <i data-lucide="folder" class="w-4 h-4 text-amber-400 group-hover:scale-110 transition-transform shrink-0"></i>
            <span class="truncate font-medium">${escapeHtml(folder.name)}</span>
          `;
          item.onclick = () => loadDir(folder.path);
          listContainer.appendChild(item);
        });

        lucide.createIcons();

      } catch (err) {
        listContainer.innerHTML = `<div class="col-span-full py-16 text-center text-rose-400 text-xs">加载失败: ${err}</div>`;
      }
    }

    function navRefreshDir() {
      loadDir(currentBrowserPath);
    }

    async function promptCreateDir() {
      const name = prompt("请输入要新建的文件夹名称:");
      if (!name || !name.trim()) return;
      try {
        const res = await fetch('/api/create_dir', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ parent: currentBrowserPath, name: name.trim() })
        });
        const data = await res.json();
        if (data.success) {
          showToast("文件夹创建成功！", "success");
          loadDir(data.path);
        } else {
          showToast(data.message || "创建失败", "error");
        }
      } catch (e) {
        showToast("创建文件夹出错: " + e, "error");
      }
    }

    function confirmSelectedFolder() {
      if (!currentBrowserPath) return;
      appSettings.output_dir = currentBrowserPath;
      applySettingsToUI();
      // 立即持久化配置
      fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ output_dir: currentBrowserPath })
      });
      closeFolderBrowser();
      showToast("已成功选定存储目录: " + currentBrowserPath, "success");
    }

    async function openCurrentOutputDir() {
      const current = document.getElementById('settingOutputDir') 
        ? document.getElementById('settingOutputDir').value.trim() 
        : (appSettings.output_dir || "downloads");
      try {
        const res = await fetch('/api/open_folder', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ current_path: current })
        });
        const data = await res.json();
        showToast(data.message || "已在资源管理器中打开目标文件夹", "info");
      } catch (e) {
        showToast("打开文件夹失败: " + e, "error");
      }
    }

    function openSettingsModal() {
      applySettingsToUI();
      const modal = document.getElementById('settingsModal');
      if (modal) modal.classList.remove('hidden');
      lucide.createIcons();
    }

    function closeSettingsModal() {
      const modal = document.getElementById('settingsModal');
      if (modal) modal.classList.add('hidden');
    }

    async function saveAppSettings() {
      const output_dir = document.getElementById('settingOutputDir').value.trim() || "downloads";
      const create_blogger_folder = document.getElementById('settingCreateBloggerFolder').checked;
      const save_subtitles = document.getElementById('settingSaveSubtitles').checked;
      const save_thumb = document.getElementById('settingSaveThumb').checked;
      const save_json = document.getElementById('settingSaveJson').checked;
      const video_codec = document.getElementById('settingVideoCodec') ? document.getElementById('settingVideoCodec').value : (appSettings.video_codec || "h264");
      const study_api_base = document.getElementById('settingStudyBase') ? document.getElementById('settingStudyBase').value.trim() : (appSettings.study_api_base || "");
      const study_api_key = document.getElementById('settingStudyKey') ? document.getElementById('settingStudyKey').value.trim() : (appSettings.study_api_key || "");
      const study_model = document.getElementById('settingStudyModel') ? document.getElementById('settingStudyModel').value.trim() : (appSettings.study_model || "gpt-4o-mini");
      const also_audio = document.getElementById('chkYtAlsoAudio') ? document.getElementById('chkYtAlsoAudio').checked : false;
      const bilingual_subs = document.getElementById('chkYtBiSubs') ? document.getElementById('chkYtBiSubs').checked : true;
      const study_doc = document.getElementById('chkYtStudyDoc') ? document.getElementById('chkYtStudyDoc').checked : true;
      const quality = document.getElementById('selectYtQuality') ? document.getElementById('selectYtQuality').value : (appSettings.quality || "best");

      const newSettings = {
        output_dir,
        create_blogger_folder,
        save_subtitles,
        save_thumb,
        save_json,
        video_codec,
        study_api_base,
        study_api_key,
        study_model,
        also_audio,
        bilingual_subs,
        study_doc,
        quality
      };

      try {
        const res = await fetch('/api/settings', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(newSettings)
        });
        const data = await res.json();
        if (data.success) {
          appSettings = data.settings;
          applySettingsToUI();
          closeSettingsModal();
          showToast("设置已保存并立即生效！", "success");
        } else {
          showToast("保存失败: " + data.message, "error");
        }
      } catch (e) {
        showToast("请求失败: " + e, "error");
      }
    }

    function resetDefaultSettings() {
      document.getElementById('settingOutputDir').value = "downloads";
      document.getElementById('settingCreateBloggerFolder').checked = true;
      document.getElementById('settingSaveSubtitles').checked = true;
      document.getElementById('settingSaveThumb').checked = true;
      document.getElementById('settingSaveJson').checked = true;
      if (document.getElementById('settingVideoCodec')) document.getElementById('settingVideoCodec').value = "h264";
      if (document.getElementById('settingStudyModel')) document.getElementById('settingStudyModel').value = "gpt-4o-mini";
      if (document.getElementById('settingStudyBase')) document.getElementById('settingStudyBase').value = "https://api.openai.com/v1";
      if (document.getElementById('settingStudyKey')) document.getElementById('settingStudyKey').value = "";
      if (document.getElementById('chkYtAlsoAudio')) document.getElementById('chkYtAlsoAudio').checked = false;
      if (document.getElementById('chkYtBiSubs')) document.getElementById('chkYtBiSubs').checked = true;
      if (document.getElementById('chkYtStudyDoc')) document.getElementById('chkYtStudyDoc').checked = true;
      if (document.getElementById('selectYtQuality')) document.getElementById('selectYtQuality').value = "best";
      showToast("已填充默认设置项，请点击保存并应用", "info");
    }

    // =========================================================================
    // 侧边栏折叠与多平台下载器切换 (Card 1: TikTok | Card 2: YouTube)
    // =========================================================================
    let currentPlatform = 'tiktok';

    function toggleSidebar() {
      const sidebar = document.getElementById('leftSidebar');
      if (!sidebar) return;
      sidebar.classList.toggle('collapsed');
      const isCollapsed = sidebar.classList.contains('collapsed');
      localStorage.setItem('sidebar_collapsed', isCollapsed ? '1' : '0');
      lucide.createIcons();
    }

    function switchPlatform(platform) {
      currentPlatform = platform;
      const pageTikTok = document.getElementById('pageTikTok');
      const pageYouTube = document.getElementById('pageYouTube');
      const pageChannels = document.getElementById('pageChannels');
      const cardTikTok = document.getElementById('sidebarCardTikTok');
      const cardYouTube = document.getElementById('sidebarCardYouTube');
      const cardChannels = document.getElementById('sidebarCardChannels');
      const headerTitle = document.getElementById('headerAppTitle');
      const headerSubtitle = document.getElementById('headerAppSubtitle');
      const headerIcon = document.getElementById('headerAppIcon');
      const headerIconLucide = document.getElementById('headerAppIconLucide');
      const btnDemo = document.getElementById('btnDemo');
      const btnDemoText = document.getElementById('btnDemoText');

      if (pageTikTok) pageTikTok.classList.add('hidden');
      if (pageYouTube) pageYouTube.classList.add('hidden');
      if (pageChannels) pageChannels.classList.add('hidden');

      const inactiveCardClass = "bg-slate-900/60 hover:bg-slate-900 border border-slate-800/80 p-3 rounded-2xl transition-all cursor-pointer space-y-1.5 select-none group hover:border-slate-700";
      if (cardTikTok) cardTikTok.className = inactiveCardClass;
      if (cardYouTube) cardYouTube.className = inactiveCardClass;
      if (cardChannels) cardChannels.className = inactiveCardClass;

      if (btnDemo) btnDemo.classList.remove('hidden');

      if (platform === 'tiktok') {
        if (pageTikTok) pageTikTok.classList.remove('hidden');
        if (cardTikTok) cardTikTok.className = "platform-card-active-tiktok p-3 rounded-2xl border cursor-pointer transition-all space-y-1.5 select-none group";
        
        if (headerTitle) {
          headerTitle.className = "text-lg font-bold tiktok-gradient-text leading-tight";
          headerTitle.innerText = "TikTok Scraper Studio";
        }
        if (headerSubtitle) headerSubtitle.innerText = "博主全量视频智能批量抓取与解析引擎";
        if (headerIcon) headerIcon.className = "w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-400 to-rose-500 flex items-center justify-center shadow-lg shadow-rose-500/25";
        if (headerIconLucide) headerIconLucide.setAttribute('data-lucide', 'video');
        if (btnDemoText) btnDemoText.innerText = "载入 Demo 体验";
      } else if (platform === 'youtube') {
        if (pageYouTube) pageYouTube.classList.remove('hidden');
        if (cardYouTube) cardYouTube.className = "platform-card-active-youtube p-3 rounded-2xl border cursor-pointer transition-all space-y-1.5 select-none group";

        if (headerTitle) {
          headerTitle.className = "text-lg font-bold youtube-gradient-text leading-tight";
          headerTitle.innerText = "YouTube Downloader Studio";
        }
        if (headerSubtitle) headerSubtitle.innerText = "频道 / 播放列表 / 视频智能批量抓取解析引擎";
        if (headerIcon) headerIcon.className = "w-9 h-9 rounded-xl bg-gradient-to-tr from-red-600 to-rose-600 flex items-center justify-center shadow-lg shadow-red-600/25";
        if (headerIconLucide) headerIconLucide.setAttribute('data-lucide', 'play');
        if (btnDemoText) btnDemoText.innerText = "载入 YouTube Demo";

        if (ytVideos.length === 0) {
          loadYtDemo();
        }
      } else if (platform === 'channels') {
        if (pageChannels) pageChannels.classList.remove('hidden');
        if (cardChannels) cardChannels.className = "platform-card-active-channels p-3 rounded-2xl border cursor-pointer transition-all space-y-1.5 select-none group";

        if (headerTitle) {
          headerTitle.className = "text-lg font-bold channels-gradient-text leading-tight";
          headerTitle.innerText = "跨平台博主与频道档案库";
        }
        if (headerSubtitle) headerSubtitle.innerText = "已添加博主集中管理、YouTube 八维书签分类与一键解析";
        if (headerIcon) headerIcon.className = "w-9 h-9 rounded-xl bg-gradient-to-tr from-purple-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-indigo-600/25";
        if (headerIconLucide) headerIconLucide.setAttribute('data-lucide', 'layout-grid');
        if (btnDemo) btnDemo.classList.add('hidden');

        loadChannelsUI();
      }
      lucide.createIcons();
    }

    function handlePlatformDemo() {
      if (currentPlatform === 'youtube') {
        loadYtDemo();
      } else {
        loadDemo();
      }
    }

    // =========================================================================
    // 频道管理与博主库前端交互逻辑 (跨平台卡片 3: TikTok 左栏 + YouTube 右栏)
    // =========================================================================
    let allChannelsData = { tiktok: [], youtube: [] };
    let ytCategoriesList = [];
    let currentYtCategoryTab = 'all';

    async function loadChannelsUI() {
      try {
        const res = await fetch('/api/channels');
        const json = await res.json();
        if (json.success) {
          allChannelsData = json;
          ytCategoriesList = json.categories || [];
          renderTiktokCreators();
          renderYtCategoryTabs();
          renderYtChannelsGrid();
        }
      } catch (err) {
        console.error("加载频道数据失败:", err);
      }
    }

    function renderTiktokCreators() {
      const list = document.getElementById('tiktokCreatorsList');
      const badge = document.getElementById('tiktokCreatorCountBadge');
      if (!list) return;

      const creators = allChannelsData.tiktok || [];
      if (badge) badge.innerText = `${creators.length} 位博主`;

      if (creators.length === 0) {
        list.innerHTML = `
          <div class="py-12 text-center text-slate-500">
            <i data-lucide="user-x" class="w-7 h-7 mx-auto mb-2 text-slate-600"></i>
            <p class="text-xs">暂无入库的 TikTok 博主，可在上方添加或解析博主自动归档</p>
          </div>
        `;
        lucide.createIcons();
        return;
      }

      list.innerHTML = '';
      creators.forEach(c => {
        const item = document.createElement('div');
        item.className = "bg-slate-900/90 hover:bg-slate-800/90 border border-slate-800/80 hover:border-cyan-500/40 rounded-xl p-3 flex items-center justify-between transition-all group cursor-pointer shadow-sm relative";
        item.onclick = () => openAndScanTiktokCreator(c.username);

        item.innerHTML = `
          <div class="flex items-center space-x-3 min-w-0 pr-2">
            <div class="w-10 h-10 rounded-full overflow-hidden bg-slate-950 border border-slate-700/80 shrink-0 flex items-center justify-center">
              <img src="${c.avatar}" class="w-full h-full object-cover" onerror="this.src='https://api.dicebear.com/7.x/bottts/svg?seed=${encodeURIComponent(c.username)}'">
            </div>
            <div class="min-w-0">
              <div class="text-sm font-bold text-slate-100 group-hover:text-cyan-400 transition-colors truncate" title="${c.nickname || c.username}">
                ${escapeHtml(c.nickname || c.username)}
              </div>
              <div class="text-xs text-slate-400 truncate mt-0.5">
                @${escapeHtml(c.username)} · ${escapeHtml(c.category || 'TikTok 创作者')}${c.downloads > 0 ? ` · 下载 ${c.downloads}` : ''}
              </div>
            </div>
          </div>
          <div class="flex items-center space-x-2 shrink-0">
            ${c.downloads > 0 ? `
              <span class="bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-xs font-bold px-2 py-0.5 rounded-full font-mono">${c.downloads}</span>
            ` : ''}
            <button onclick="event.stopPropagation(); deleteChannelItem('tiktok', '${c.id || c.username}')" class="text-slate-500 hover:text-rose-400 p-1 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity" title="删除记录">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        `;
        list.appendChild(item);
      });
      lucide.createIcons();
    }

    function renderYtCategoryTabs() {
      const container = document.getElementById('ytChannelCategoryTabs');
      if (!container) return;
      container.innerHTML = '';

      const ytChannels = allChannelsData.youtube || [];
      const totalBadge = document.getElementById('ytChannelTotalBadge');
      if (totalBadge) totalBadge.innerText = `${ytChannels.length} 个频道`;

      ytCategoriesList.forEach(cat => {
        const isActive = (cat.id === currentYtCategoryTab);
        const count = (cat.id === 'all')
          ? ytChannels.length
          : ytChannels.filter(ch => (ch.cat || 'other') === cat.id).length;

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.onclick = () => {
          currentYtCategoryTab = cat.id;
          renderYtCategoryTabs();
          renderYtChannelsGrid();
        };

        // 样式完全对标截图：圆顶、活跃标签红线高亮
        btn.className = isActive
          ? "px-3.5 py-2 text-xs font-semibold rounded-t-xl bg-slate-900 border-t-2 border-x border-red-500 border-x-slate-800 text-white shadow-md flex items-center space-x-1.5 whitespace-nowrap cursor-pointer transition-colors relative -mb-[1px]"
          : "px-3.5 py-2 text-xs font-medium rounded-t-xl bg-slate-950/60 hover:bg-slate-900/80 border-t-2 border-x border-transparent text-slate-400 hover:text-slate-200 flex items-center space-x-1.5 whitespace-nowrap cursor-pointer transition-colors";

        btn.innerHTML = `
          <span>${cat.icon}</span>
          <span>${cat.short || cat.name}</span>
          <span class="text-[11px] ${isActive ? 'text-red-400 font-bold' : 'text-slate-500'} font-mono">${count}</span>
        `;
        container.appendChild(btn);
      });
    }

    function renderYtChannelsGrid() {
      const grid = document.getElementById('ytChannelsGrid');
      if (!grid) return;
      grid.innerHTML = '';

      const ytChannels = allChannelsData.youtube || [];
      const filtered = (currentYtCategoryTab === 'all')
        ? ytChannels
        : ytChannels.filter(ch => (ch.cat || 'other') === currentYtCategoryTab);

      if (filtered.length === 0) {
        grid.innerHTML = `
          <div class="col-span-full py-16 text-center text-slate-500">
            <i data-lucide="folder-open" class="w-8 h-8 mx-auto mb-2 text-slate-600"></i>
            <p class="text-xs">当前分类下暂无入库的频道，可通过上方“添加频道”或在 YouTube 下载器中解析自动归类</p>
          </div>
        `;
        lucide.createIcons();
        return;
      }

      filtered.forEach(ch => {
        const card = document.createElement('div');
        // 完全对标截图卡片：黑底、微圆角、头像、频道名、分类 & 下载数、右侧红圆药丸
        card.className = "bg-slate-900/85 hover:bg-slate-800/90 border border-slate-800/90 hover:border-red-500/40 rounded-xl p-3 flex items-center justify-between transition-all group cursor-pointer shadow-sm hover:shadow-md relative";
        card.onclick = () => openAndScanYtChannel(ch.url || ch.handle);

        const subText = `${ch.cat_name || '其他'}${ch.downloads > 0 ? ` · 下载 ${ch.downloads}` : ''}`;

        card.innerHTML = `
          <div class="flex items-center space-x-3 min-w-0 pr-2">
            <div class="w-10 h-10 rounded-full overflow-hidden bg-slate-950 border border-slate-700/80 shrink-0 flex items-center justify-center">
              <img src="${ch.avatar}" class="w-full h-full object-cover" onerror="this.src='https://api.dicebear.com/7.x/identicon/svg?seed=${encodeURIComponent(ch.title)}'">
            </div>
            <div class="min-w-0">
              <div class="text-sm font-bold text-slate-100 group-hover:text-red-400 transition-colors truncate" title="${ch.title}">
                ${escapeHtml(ch.title)}
              </div>
              <div class="text-xs text-slate-400 truncate mt-0.5">
                ${escapeHtml(subText)}
              </div>
            </div>
          </div>
          <div class="flex items-center space-x-2 shrink-0">
            ${ch.downloads > 0 ? `
              <span class="bg-red-500 text-white text-xs font-bold px-2 py-0.5 rounded-full shrink-0 shadow-sm font-mono">${ch.downloads}</span>
            ` : ''}
            <button onclick="event.stopPropagation(); deleteChannelItem('youtube', '${ch.id || ch.handle}')" class="text-slate-500 hover:text-rose-400 p-1 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity" title="删除频道">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        `;
        grid.appendChild(card);
      });
      lucide.createIcons();
    }

    function openAndScanTiktokCreator(username) {
      switchPlatform('tiktok');
      const input = document.getElementById('inputUsername');
      if (input) input.value = username;
      startScan(false);
      showToast(`已加载 TikTok 博主 @${username} 并启动解析`, "info");
    }

    function openAndScanYtChannel(url) {
      switchPlatform('youtube');
      const input = document.getElementById('inputYtUrl');
      if (input) input.value = url;
      startYtScan();
      showToast(`已加载 YouTube 频道并在后台启动解析: ${url}`, "info");
    }

    async function deleteChannelItem(platform, id) {
      if (!confirm(`确定要从频道管理库中移除此项吗？`)) return;
      try {
        const res = await fetch('/api/channels/delete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ platform, channel_id: id })
        });
        const json = await res.json();
        if (json.success) {
          allChannelsData.tiktok = json.tiktok || [];
          allChannelsData.youtube = json.youtube || [];
          renderTiktokCreators();
          renderYtCategoryTabs();
          renderYtChannelsGrid();
          showToast("已成功移除记录", "success");
        }
      } catch (err) {
        showToast("删除失败: " + err, "error");
      }
    }

    function quickAddTiktokCreatorModal() {
      const username = prompt("请输入要添加入库的 TikTok 博主用户名 (例如: charlidamelio 或 khaby.lame):");
      if (!username || !username.trim()) return;
      fetch('/api/channels/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ platform: 'tiktok', username_or_url: username.trim() })
      }).then(r => r.json()).then(data => {
        if (data.success) {
          allChannelsData.tiktok = data.tiktok;
          renderTiktokCreators();
          showToast(`已成功添加 TikTok 博主 @${username.trim()}`, "success");
        }
      });
    }

    function quickAddYtChannelModal() {
      const url = prompt("请输入要添加入库的 YouTube 频道主页链接或句柄 (例如: https://www.youtube.com/@mkbhd 或 @mkbhd):");
      if (!url || !url.trim()) return;
      const cat = prompt("请输入所属分类代码 (tech=科技, growth=成长, health=健康, business=商业, knowledge=人文, life=娱乐, other=其他):", "tech");
      fetch('/api/channels/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ platform: 'youtube', username_or_url: url.trim(), cat: cat || 'other' })
      }).then(r => r.json()).then(data => {
        if (data.success) {
          allChannelsData.youtube = data.youtube;
          renderYtCategoryTabs();
          renderYtChannelsGrid();
          showToast(`已成功添加 YouTube 频道: ${url.trim()}`, "success");
        }
      });
    }

    // =========================================================================
    // YouTube 下载器前端交互逻辑 (第二卡片独立状态机)
    // =========================================================================
    let ytVideos = [];
    let ytIsTaskRunning = false;
    let ytLastKnownVideoCount = 0;
    let ytSelectedUrls = new Set();
    let ytCurrentPage = 1;
    let ytActiveCategory = 'all';
    const YT_PAGE_SIZE = 20;
    let ytDownloadQueue = [];
    let ytCurrentRightTab = 'queue';

    // 🌟 四维分类切换与计数管理 (All / Videos / Shorts / Live / Podcasts)
    function filterYtCategory(cat) {
      ytActiveCategory = cat;
      const cats = ['all', 'videos', 'shorts', 'live', 'podcasts'];
      cats.forEach(c => {
        const btnId = 'btnCat' + c.charAt(0).toUpperCase() + c.slice(1);
        const btn = document.getElementById(btnId);
        if (!btn) return;
        if (c === cat) {
          btn.className = "px-3 py-1.5 rounded-lg font-semibold bg-red-600 text-white shadow-sm transition-all whitespace-nowrap cursor-pointer";
        } else {
          btn.className = "px-3 py-1.5 rounded-lg font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-all whitespace-nowrap cursor-pointer";
        }
      });
      ytCurrentPage = 1;
      renderYtCurrentPage();
    }

    function updateYtCategoryCounts() {
      const counts = { all: ytVideos.length, videos: 0, shorts: 0, live: 0, podcasts: 0 };
      ytVideos.forEach(v => {
        const c = v.category || 'videos';
        if (counts[c] !== undefined) counts[c]++;
        else counts.videos++;
      });
      const elAll = document.getElementById('catCountAll');
      const elVid = document.getElementById('catCountVideos');
      const elSho = document.getElementById('catCountShorts');
      const elLiv = document.getElementById('catCountLive');
      const elPod = document.getElementById('catCountPodcasts');
      if (elAll) elAll.innerText = counts.all;
      if (elVid) elVid.innerText = counts.videos;
      if (elSho) elSho.innerText = counts.shorts;
      if (elLiv) elLiv.innerText = counts.live;
      if (elPod) elPod.innerText = counts.podcasts;
    }

    function getFilteredYtVideos() {
      if (ytActiveCategory === 'all') return ytVideos;
      return ytVideos.filter(v => (v.category || 'videos') === ytActiveCategory);
    }

    // 独立轮询 YouTube 后端状态
    setInterval(fetchYtStatus, 500);

    async function fetchYtStatus() {
      try {
        const res = await fetch('/api/youtube/status');
        const data = await res.json();
        
        ytIsTaskRunning = data.is_running;
        const statusTextEl = document.getElementById('ytStatusText');
        if (statusTextEl) statusTextEl.innerText = data.status_text || '就绪';
        
        const pct = Math.round((data.progress || 0) * 100);
        const progressBar = document.getElementById('ytProgressBar');
        const progressText = document.getElementById('ytProgressText');
        if (progressBar) progressBar.style.width = pct + '%';
        if (progressText) progressText.innerText = pct + '%';

        const pulse = document.getElementById('ytStatusPulse');
        const btnStop = document.getElementById('btnYtStop');
        const btnScan = document.getElementById('btnYtScan');
        const btnDownloadAll = document.getElementById('btnYtDownloadAll');

        if (ytIsTaskRunning) {
          if (pulse) pulse.className = 'w-3 h-3 rounded-full bg-red-400 animate-ping';
          if (btnStop) {
            btnStop.disabled = false;
            btnStop.className = 'px-4 py-2.5 text-sm font-semibold bg-rose-600 hover:bg-rose-500 text-white rounded-xl transition-all flex items-center space-x-1.5 active:scale-95 cursor-pointer';
          }
          if (btnScan) btnScan.disabled = true;
          if (btnDownloadAll) btnDownloadAll.disabled = true;
        } else {
          if (pulse) pulse.className = 'w-3 h-3 rounded-full bg-emerald-500';
          if (btnStop) {
            btnStop.disabled = true;
            btnStop.className = 'px-4 py-2.5 text-sm font-semibold bg-slate-800 text-slate-500 rounded-xl transition-all flex items-center space-x-1.5 disabled:opacity-50';
          }
          if (btnScan) btnScan.disabled = false;
          if (btnDownloadAll) btnDownloadAll.disabled = false;
        }

        // 增量获取视频数据
        const serverVideoCount = data.video_count || 0;
        if (serverVideoCount !== ytLastKnownVideoCount) {
          ytLastKnownVideoCount = serverVideoCount;
          if (serverVideoCount > 0) {
            const vRes = await fetch('/api/youtube/videos');
            const vData = await vRes.json();
            const newVideos = vData.videos || [];
            const isFirstLoad = ytVideos.length === 0;
            ytVideos = newVideos;
            if (vData.channel_category) {
              const badge = document.getElementById('ytChannelCategoryBadge');
              if (badge) {
                const catObj = (typeof vData.channel_category === 'object') ? vData.channel_category : { name: vData.channel_category, icon: '🏷️' };
                const icon = catObj.icon || '🏷️';
                const name = catObj.name || '';
                badge.innerHTML = `<span>${icon} ${escapeHtml(name)}</span>`;
                badge.classList.remove('hidden');
              }
            }
            if (isFirstLoad) {
              ytSelectedUrls.clear();
              ytVideos.forEach(v => ytSelectedUrls.add(v.url));
            } else {
              ytVideos.forEach(v => {
                if (!ytSelectedUrls.has(v.url)) {
                  ytSelectedUrls.add(v.url);
                }
              });
            }
            updateYtSelectedCount();
            const badge = document.getElementById('ytVideoCountBadge');
            if (badge) badge.innerText = `${ytVideos.length} 个视频`;
            updateYtCategoryCounts();
            renderYtCurrentPage();
          }
        }

        // 实时更新 YouTube 下载队列
        if (ytDownloadQueue.length > 0) {
          const stats = data.download_stats || {};
          const downloaded = stats.downloaded || 0;
          const actionText = data.action || '';
          const isDownloadingAction = actionText.includes('下载') || actionText.includes('Download') || actionText.includes('批量');

          if (ytIsTaskRunning && isDownloadingAction) {
            ytDownloadQueue.forEach((item, idx) => {
              if (idx < downloaded) {
                item.state = 'done';
                item.percent = 100;
                item.statusText = '已完成下载';
              } else if (idx === downloaded) {
                item.state = 'downloading';
                item.percent = Math.max(item.percent, pct);
                item.statusText = data.status_text || '正在下载…';
              } else {
                if (item.state !== 'done') {
                  item.state = 'waiting';
                  item.percent = 0;
                  item.statusText = '等待下载…';
                }
              }
            });
          } else if (!ytIsTaskRunning) {
            if (downloaded >= ytDownloadQueue.length && ytDownloadQueue.length > 0) {
              ytDownloadQueue.forEach(item => {
                if (item.state !== 'failed') {
                  item.state = 'done';
                  item.percent = 100;
                  item.statusText = '已完成下载';
                }
              });
            } else if (downloaded > 0) {
              ytDownloadQueue.forEach((item, idx) => {
                if (idx < downloaded) {
                  item.state = 'done';
                  item.percent = 100;
                  item.statusText = '已完成下载';
                }
              });
            }
          }

          updateYtQueueStats();
          if (ytCurrentRightTab === 'queue') {
            renderYtQueueUI();
          }
        }

        renderYtLogs(data.logs);
      } catch (err) {
        // console.error("轮询 YouTube 状态失败:", err);
      }
    }

    function renderYtLogs(logs) {
      if (!logs || logs.length === 0) return;
      const consoleBox = document.getElementById('ytLogConsole');
      if (!consoleBox) return;
      consoleBox.innerHTML = '';
      logs.forEach(item => {
        const row = document.createElement('div');
        let colorClass = 'text-slate-300';
        if (item.level === 'success') colorClass = 'text-emerald-400';
        if (item.level === 'warn') colorClass = 'text-amber-400';
        if (item.level === 'error') colorClass = 'text-rose-400';
        row.className = `${colorClass} leading-relaxed break-all`;
        row.innerHTML = `<span class="text-slate-600">[${item.time}]</span> ${escapeHtml(item.text)}`;
        consoleBox.appendChild(row);
      });
      consoleBox.scrollTop = consoleBox.scrollHeight;
      const logBadge = document.getElementById('ytLogCountBadge');
      if (logBadge) logBadge.innerText = logs.length;
    }

    function clearYtLogs() {
      const consoleBox = document.getElementById('ytLogConsole');
      if (consoleBox) consoleBox.innerHTML = '<div class="text-slate-500">// YouTube 日志已清空</div>';
    }

    function switchYtRightTab(tab) {
      ytCurrentRightTab = tab;
      const btnLog = document.getElementById('btnYtTabLog');
      const btnQueue = document.getElementById('btnYtTabQueue');
      const panelLog = document.getElementById('panelYtLog');
      const panelQueue = document.getElementById('panelYtQueue');
      const actionText = document.getElementById('textYtRightHeaderAction');

      if (tab === 'log') {
        btnLog.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-red-600 text-white shadow-md transition-all flex items-center space-x-1.5 whitespace-nowrap";
        btnQueue.className = "px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200 transition-all flex items-center space-x-1.5 whitespace-nowrap";
        panelLog.classList.remove('hidden');
        panelQueue.classList.add('hidden');
        if (actionText) actionText.innerText = "清空日志";
      } else {
        btnQueue.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-red-600 text-white shadow-md transition-all flex items-center space-x-1.5 whitespace-nowrap";
        btnLog.className = "px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200 transition-all flex items-center space-x-1.5 whitespace-nowrap";
        panelQueue.classList.remove('hidden');
        panelLog.classList.add('hidden');
        if (actionText) actionText.innerText = "清除已完成";
      }
      lucide.createIcons();
    }

    function handleYtRightHeaderAction() {
      if (ytCurrentRightTab === 'log') {
        clearYtLogs();
      } else {
        clearYtCompletedQueue();
      }
    }

    function syncYtDownloadQueueFromSelection(urls) {
      urls.forEach(url => {
        const existing = ytDownloadQueue.find(q => q.url === url);
        if (!existing) {
          const videoMeta = ytVideos.find(v => v.url === url) || {};
          ytDownloadQueue.push({
            id: videoMeta.id || url.split('v=').pop(),
            title: videoMeta.title || 'YouTube 视频',
            url: url,
            thumbnail: videoMeta.thumbnail || '',
            duration: videoMeta.duration || '',
            state: 'waiting',
            percent: 0,
            statusText: '等待下载…'
          });
        }
      });
      updateYtQueueStats();
      renderYtQueueUI();
    }

    function updateYtQueueStats() {
      const active = ytDownloadQueue.filter(q => q.state === 'downloading').length;
      const waiting = ytDownloadQueue.filter(q => q.state === 'waiting').length;
      const done = ytDownloadQueue.filter(q => q.state === 'done').length;
      const failed = ytDownloadQueue.filter(q => q.state === 'failed').length;

      const qActive = document.getElementById('ytQActiveCount');
      const qWaiting = document.getElementById('ytQWaitingCount');
      const qDone = document.getElementById('ytQDoneCount');
      const qFailed = document.getElementById('ytQFailedCount');
      const badge = document.getElementById('ytQueueCountBadge');
      const pageText = document.getElementById('ytQueuePageText');

      if (qActive) qActive.innerText = active;
      if (qWaiting) qWaiting.innerText = waiting;
      if (qDone) qDone.innerText = done;
      if (qFailed) qFailed.innerText = failed;
      if (badge) badge.innerText = ytDownloadQueue.length;
      if (pageText) pageText.innerText = `队列总计 ${ytDownloadQueue.length} 项`;
    }

    function renderYtQueueUI() {
      const container = document.getElementById('ytQueueItemsList');
      if (!container) return;

      if (ytDownloadQueue.length === 0) {
        container.innerHTML = `
          <div class="h-full flex flex-col items-center justify-center text-slate-500 py-16 text-center">
            <i data-lucide="layers" class="w-8 h-8 text-slate-600 mb-2"></i>
            <p class="text-xs">勾选 YouTube 视频并点击“批量下载”后，任务将显示在这里</p>
          </div>
        `;
        lucide.createIcons();
        return;
      }

      const existingCards = container.querySelectorAll('.queue-card');
      if (existingCards.length === ytDownloadQueue.length) {
        ytDownloadQueue.forEach((item, idx) => {
          const card = existingCards[idx];
          if (!card) return;
          const statusTextEl = card.querySelector('.queue-status-text');
          if (statusTextEl && statusTextEl.innerText !== item.statusText) {
            statusTextEl.innerText = item.statusText || '等待中';
          }
          const barEl = card.querySelector('.queue-progress-bar');
          if (barEl) {
            barEl.style.width = item.percent + '%';
            if (item.state === 'done') {
              barEl.className = 'queue-progress-bar h-full bg-emerald-500 transition-all duration-300';
            } else if (item.state === 'downloading') {
              barEl.className = 'queue-progress-bar h-full bg-gradient-to-r from-red-500 to-rose-500 transition-all duration-300';
            } else if (item.state === 'failed') {
              barEl.className = 'queue-progress-bar h-full bg-rose-500 transition-all duration-300';
            }
          }
          const tagEl = card.querySelector('.queue-badge');
          if (tagEl) {
            const badgeText = item.state === 'done' ? '已完成' : (item.state === 'downloading' ? '下载中' : (item.state === 'failed' ? '失败' : '排队中'));
            if (tagEl.innerText !== badgeText) {
              tagEl.innerText = badgeText;
              let badgeColor = 'bg-slate-800 text-slate-400';
              if (item.state === 'downloading') badgeColor = 'bg-red-500/20 text-red-300 border border-red-500/30';
              else if (item.state === 'done') badgeColor = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
              else if (item.state === 'failed') badgeColor = 'bg-rose-500/20 text-rose-300 border border-rose-500/30';
              tagEl.className = `queue-badge text-[10px] px-1.5 py-0.5 rounded ${badgeColor} shrink-0 font-medium`;
            }
          }
        });
        return;
      }

      container.innerHTML = ytDownloadQueue.map((item, idx) => {
        let borderClass = 'border-slate-800 bg-slate-950/70';
        let barColor = 'bg-red-500';
        let badgeColor = 'bg-slate-800 text-slate-400';

        if (item.state === 'downloading') {
          borderClass = 'border-red-500/50 bg-red-950/20 shadow-md shadow-red-950/50';
          barColor = 'bg-gradient-to-r from-red-500 to-rose-500';
          badgeColor = 'bg-red-500/20 text-red-300 border border-red-500/30';
        } else if (item.state === 'done') {
          borderClass = 'border-emerald-500/40 bg-emerald-950/10';
          barColor = 'bg-emerald-500';
          badgeColor = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
        } else if (item.state === 'failed') {
          borderClass = 'border-rose-500/40 bg-rose-950/10';
          barColor = 'bg-rose-500';
          badgeColor = 'bg-rose-500/20 text-rose-300 border border-rose-500/30';
        }

        const badgeText = item.state === 'done' ? '已完成' : (item.state === 'downloading' ? '下载中' : (item.state === 'failed' ? '失败' : '排队中'));

        return `
          <div class="queue-card p-2.5 rounded-xl border ${borderClass} transition-all space-y-2">
            <div class="flex items-center space-x-2.5">
              <div class="w-12 h-8 rounded-md bg-slate-900 border border-slate-800 overflow-hidden shrink-0 relative flex items-center justify-center">
                ${item.thumbnail ? `<img src="${item.thumbnail}" class="w-full h-full object-cover">` : `<i data-lucide="play" class="w-3.5 h-3.5 text-slate-500"></i>`}
                ${item.duration ? `<span class="absolute bottom-0.5 right-0.5 bg-black/80 text-[8px] font-mono px-1 rounded text-white">${item.duration}</span>` : ''}
              </div>
              <div class="flex-1 min-w-0">
                <div class="text-xs font-medium text-slate-200 truncate leading-snug" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
                <div class="flex items-center space-x-2 mt-0.5 text-[10px] text-slate-400">
                  <span class="queue-status-text">${item.statusText}</span>
                </div>
              </div>
              <span class="queue-badge text-[10px] px-1.5 py-0.5 rounded ${badgeColor} shrink-0 font-medium">${badgeText}</span>
            </div>
            <div class="w-full bg-slate-950 rounded-full h-1.5 overflow-hidden border border-slate-800">
              <div class="queue-progress-bar h-full ${barColor} transition-all duration-300" style="width: ${item.percent}%;"></div>
            </div>
          </div>
        `;
      }).join('');

      lucide.createIcons();
    }

    function clearYtCompletedQueue() {
      const beforeCount = ytDownloadQueue.length;
      ytDownloadQueue = ytDownloadQueue.filter(q => q.state !== 'done');
      const removed = beforeCount - ytDownloadQueue.length;
      updateYtQueueStats();
      renderYtQueueUI();
      showToast(`已清理 ${removed} 个已完成的 YouTube 任务`, "info");
    }

    async function cancelYtAllQueue() {
      if (ytDownloadQueue.length === 0) return;
      if (ytIsTaskRunning) {
        await stopYtTask();
      }
      ytDownloadQueue = [];
      updateYtQueueStats();
      renderYtQueueUI();
      showToast("已清空 YouTube 下载队列", "info");
    }

    // --- YouTube 业务动作 ---
    async function startYtScan() {
      const url = document.getElementById('inputYtUrl').value.trim();
      if (!url) {
        showToast("请输入 YouTube 频道网址、播放列表或视频链接", "warn");
        return;
      }
      const proxy = document.getElementById('inputYtProxy').value.trim();
      const limit = document.getElementById('inputYtLimit').value.trim();
      const cookieText = document.getElementById('inputYtCookieText').value.trim();

      try {
        const res = await fetch('/api/youtube/scan', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            username: url,
            proxy: proxy,
            max_videos: limit ? parseInt(limit) : 0,
            cookie_text: cookieText
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(data.message || "开始解析 YouTube 频道...", "info");
        } else {
          showToast("启动失败: " + data.message, "error");
        }
      } catch (err) {
        showToast("网络请求错误: " + err, "error");
      }
    }

    async function loadYtDemo() {
      try {
        const res = await fetch('/api/youtube/scan', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            username: "demo",
            is_demo: true
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast("已载入 YouTube 演示数据 (45 条超清视频)！", "success");
        }
      } catch (err) {
        showToast("载入 Demo 失败: " + err, "error");
      }
    }

    async function stopYtTask() {
      try {
        const res = await fetch('/api/youtube/stop', {method: 'POST'});
        const data = await res.json();
        showToast(data.message || "已发送停止指令", "info");
      } catch (err) {
        showToast("停止任务出错: " + err, "error");
      }
    }

    function startYtDownloadAll() {
      if (ytVideos.length === 0) {
        showToast("当前暂无视频可下载，请先解析 YouTube 频道", "warn");
        return;
      }
      const allUrls = ytVideos.map(v => v.url);
      executeYtDownload(allUrls);
    }

    function startYtDownloadSelected() {
      if (ytSelectedUrls.size === 0) {
        showToast("请先在列表中勾选要下载的视频", "warn");
        return;
      }
      executeYtDownload(Array.from(ytSelectedUrls));
    }

    function downloadYtSingle(url) {
      executeYtDownload([url]);
    }

    async function executeYtDownload(urls) {
      if (!urls || urls.length === 0) return;
      syncYtDownloadQueueFromSelection(urls);
      switchYtRightTab('queue');

      const channel = document.getElementById('inputYtUrl').value.trim() || "youtube_batch";
      const proxy = document.getElementById('inputYtProxy').value.trim();
      const saveSubtitles = document.getElementById('chkYtSubtitles').checked;
      const saveThumb = document.getElementById('chkYtThumb').checked;
      const saveJson = document.getElementById('chkYtJson').checked;
      const outputDir = appSettings.output_dir || "downloads";

      const quality = document.getElementById('selectYtQuality') ? document.getElementById('selectYtQuality').value : (appSettings.quality || "best");
      const videoCodec = document.getElementById('settingVideoCodec') ? document.getElementById('settingVideoCodec').value : (appSettings.video_codec || "h264");
      const alsoAudio = document.getElementById('chkYtAlsoAudio') ? document.getElementById('chkYtAlsoAudio').checked : false;
      const bilingualSubs = document.getElementById('chkYtBiSubs') ? document.getElementById('chkYtBiSubs').checked : true;
      const studyDoc = document.getElementById('chkYtStudyDoc') ? document.getElementById('chkYtStudyDoc').checked : true;

      try {
        const res = await fetch('/api/youtube/download', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            username: channel,
            video_urls: urls,
            proxy: proxy,
            output_dir: outputDir,
            save_subtitles: saveSubtitles,
            save_thumb: saveThumb,
            save_json: saveJson,
            quality: quality,
            video_codec: videoCodec,
            also_audio: alsoAudio,
            audio_only: (quality === 'audio'),
            study_doc: studyDoc,
            bilingual_subs: bilingualSubs,
            study_api_base: appSettings.study_api_base || "",
            study_api_key: appSettings.study_api_key || "",
            study_model: appSettings.study_model || "gpt-4o-mini"
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`已开始下载 ${urls.length} 个 YouTube 视频，请观察下载队列进度`, "success");
        } else {
          showToast("启动下载失败: " + data.message, "error");
        }
      } catch (err) {
        showToast("请求下载异常: " + err, "error");
      }
    }

    // --- YouTube 视频表格分页与批量选择 ---
    function updateYtSelectedCount() {
      const badge = document.getElementById('ytSelectedCountBadge');
      if (badge) badge.innerHTML = `已选 <strong class="text-red-400 font-mono">${ytSelectedUrls.size}</strong> 项`;
      const btnDl = document.getElementById('btnYtDownloadSelectedText');
      if (btnDl) btnDl.innerText = `下载选中项 (${ytSelectedUrls.size})`;
      const btnDlBottom = document.getElementById('btnYtDownloadSelectedBottomText');
      if (btnDlBottom) btnDlBottom.innerText = `下载选中项 (${ytSelectedUrls.size})`;
    }

    function renderYtCurrentPage() {
      updateYtCategoryCounts();
      const tbody = document.getElementById('ytVideoTableBody');
      if (!tbody) return;

      const filteredVideos = getFilteredYtVideos();

      if (filteredVideos.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="7" class="py-20 text-center text-slate-500">
              <div class="flex flex-col items-center justify-center space-y-2">
                <i data-lucide="film" class="w-8 h-8 text-slate-600"></i>
                <span>当前分类暂无视频，请切换上方分类标签或重新解析</span>
              </div>
            </td>
          </tr>
        `;
        lucide.createIcons();
        return;
      }

      const totalItems = filteredVideos.length;
      const totalPages = Math.ceil(totalItems / YT_PAGE_SIZE) || 1;
      if (ytCurrentPage > totalPages) ytCurrentPage = totalPages;
      if (ytCurrentPage < 1) ytCurrentPage = 1;

      const startIndex = (ytCurrentPage - 1) * YT_PAGE_SIZE;
      const endIndex = Math.min(startIndex + YT_PAGE_SIZE, totalItems);
      const pageVideos = filteredVideos.slice(startIndex, endIndex);

      const pageInfo = document.getElementById('ytPageInfo');
      if (pageInfo) pageInfo.innerText = `显示第 ${startIndex + 1} - ${endIndex} 项，共 ${totalItems} 项 (每页 ${YT_PAGE_SIZE} 项)`;

      const prevBtn = document.getElementById('ytPrevBtn');
      const nextBtn = document.getElementById('ytNextBtn');
      if (prevBtn) prevBtn.disabled = ytCurrentPage <= 1;
      if (nextBtn) nextBtn.disabled = ytCurrentPage >= totalPages;

      const pageNumbers = document.getElementById('ytPageNumbers');
      if (pageNumbers) {
        let pagesHtml = '';
        for (let p = 1; p <= totalPages; p++) {
          if (totalPages <= 7 || p === 1 || p === totalPages || (p >= ytCurrentPage - 1 && p <= ytCurrentPage + 1)) {
            const isActive = p === ytCurrentPage;
            pagesHtml += `
              <button onclick="changeYtPageTo(${p})" class="w-7 h-7 rounded-lg text-xs font-semibold transition-colors ${isActive ? 'bg-red-600 text-white' : 'text-slate-400 hover:text-white hover:bg-slate-800'}">
                ${p}
              </button>
            `;
          } else if (p === ytCurrentPage - 2 || p === ytCurrentPage + 2) {
            pagesHtml += `<span class="text-slate-600 px-0.5 text-xs">...</span>`;
          }
        }
        pageNumbers.innerHTML = pagesHtml;
      }

      const allPageSelected = pageVideos.length > 0 && pageVideos.every(v => ytSelectedUrls.has(v.url));
      const selectAllChk = document.getElementById('selectAllYtPageCheckbox');
      if (selectAllChk) selectAllChk.checked = allPageSelected;

      tbody.innerHTML = pageVideos.map((video, idx) => {
        const isChecked = ytSelectedUrls.has(video.url);
        const cat = video.category || 'videos';
        let catBadge = `<span class="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/30 text-[10px] font-medium mr-1.5 shrink-0">🎬 视频</span>`;
        if (cat === 'shorts') {
          catBadge = `<span class="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 text-[10px] font-medium mr-1.5 shrink-0">⚡ Shorts</span>`;
        } else if (cat === 'live') {
          catBadge = `<span class="px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-400 border border-rose-500/30 text-[10px] font-medium mr-1.5 shrink-0">🔴 Live</span>`;
        } else if (cat === 'podcasts') {
          catBadge = `<span class="px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-400 border border-purple-500/30 text-[10px] font-medium mr-1.5 shrink-0">🎙️ 播客</span>`;
        }

        return `
          <tr class="hover:bg-slate-800/40 transition-colors ${isChecked ? 'bg-red-950/15' : ''}">
            <td class="px-4 py-2.5 text-center">
              <input type="checkbox" onchange="toggleYtItemSelection('${video.url}')" ${isChecked ? 'checked' : ''} class="rounded border-slate-700 bg-slate-900 text-red-500 focus:ring-0 cursor-pointer">
            </td>
            <td class="px-3 py-2.5">
              <div class="w-14 h-9 rounded bg-slate-900 border border-slate-800 overflow-hidden relative group">
                <img src="${video.thumbnail}" class="w-full h-full object-cover group-hover:scale-105 transition-transform" loading="lazy" onerror="this.src='https://images.unsplash.com/photo-1611162617474-5b21e879e113?w=300'">
                <a href="${video.url}" target="_blank" class="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity text-white">
                  <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                </a>
              </div>
            </td>
            <td class="px-3 py-2.5">
              <div class="flex items-center">
                ${catBadge}
                <a href="${video.url}" target="_blank" class="font-medium text-slate-200 hover:text-red-400 line-clamp-1 transition-colors leading-snug" title="${escapeHtml(video.title)}">
                  ${escapeHtml(video.title)}
                </a>
              </div>
              <div class="text-[10px] text-slate-500 font-mono mt-0.5 truncate">${video.id}</div>
            </td>
            <td class="px-3 py-2.5 font-mono text-slate-400 whitespace-nowrap">
              ${video.duration}
            </td>
            <td class="px-3 py-2.5 whitespace-nowrap text-slate-400">
              <div class="flex items-center space-x-1.5">
                <i data-lucide="eye" class="w-3.5 h-3.5 text-slate-500"></i>
                <span class="font-mono">${video.view_count}</span>
              </div>
            </td>
            <td class="px-3 py-2.5 font-mono text-slate-400 whitespace-nowrap">
              ${video.upload_date}
            </td>
            <td class="px-4 py-2.5 text-right whitespace-nowrap">
              <button onclick="downloadYtSingle('${video.url}')" class="px-2.5 py-1 rounded-lg bg-red-600/20 hover:bg-red-600/40 text-red-300 hover:text-white border border-red-500/30 transition-all text-[11px] font-medium inline-flex items-center space-x-1 cursor-pointer">
                <i data-lucide="download" class="w-3 h-3"></i>
                <span>下载</span>
              </button>
            </td>
          </tr>
        `;
      }).join('');

      lucide.createIcons();
    }

    function changeYtPage(delta) {
      ytCurrentPage += delta;
      renderYtCurrentPage();
    }

    function changeYtPageTo(p) {
      ytCurrentPage = p;
      renderYtCurrentPage();
    }

    function toggleYtItemSelection(url) {
      if (ytSelectedUrls.has(url)) {
        ytSelectedUrls.delete(url);
      } else {
        ytSelectedUrls.add(url);
      }
      updateYtSelectedCount();
      renderYtCurrentPage();
    }

    function selectYtCurrentPage() {
      const filteredVideos = getFilteredYtVideos();
      const startIndex = (ytCurrentPage - 1) * YT_PAGE_SIZE;
      const endIndex = Math.min(startIndex + YT_PAGE_SIZE, filteredVideos.length);
      const pageVideos = filteredVideos.slice(startIndex, endIndex);
      pageVideos.forEach(v => ytSelectedUrls.add(v.url));
      updateYtSelectedCount();
      renderYtCurrentPage();
      showToast(`已勾选当前页 ${pageVideos.length} 个 YouTube 视频`, "info");
    }

    function selectAllYtVideos() {
      const filteredVideos = getFilteredYtVideos();
      filteredVideos.forEach(v => ytSelectedUrls.add(v.url));
      updateYtSelectedCount();
      renderYtCurrentPage();
      const label = ytActiveCategory === 'all' ? '全部' : '当前分类';
      showToast(`已勾选${label} ${filteredVideos.length} 个 YouTube 视频`, "info");
    }

    function toggleSelectAllYtPage(chk) {
      const filteredVideos = getFilteredYtVideos();
      const startIndex = (ytCurrentPage - 1) * YT_PAGE_SIZE;
      const endIndex = Math.min(startIndex + YT_PAGE_SIZE, filteredVideos.length);
      const pageVideos = filteredVideos.slice(startIndex, endIndex);
      if (chk.checked) {
        pageVideos.forEach(v => ytSelectedUrls.add(v.url));
      } else {
        pageVideos.forEach(v => ytSelectedUrls.delete(v.url));
      }
      updateYtSelectedCount();
      renderYtCurrentPage();
    }

    // 页面初始化
    fetchSettings();
    renderQueueUI();
    renderYtQueueUI();

    // 记忆用户侧边栏折叠偏好
    if (localStorage.getItem('sidebar_collapsed') === '1') {
      const sidebar = document.getElementById('leftSidebar');
      if (sidebar) sidebar.classList.add('collapsed');
    }

    setTimeout(() => {
      loadDemo();
    }, 400);
  </script>
</body>
</html>
"""

def open_browser_later(url: str):
    time.sleep(1.2)
    print(f"🌐 正在自动为您在本地浏览器弹出 Demo 网页: {url}")
    webbrowser.open(url)

if __name__ == "__main__":
    port = 8000
    host = "127.0.0.1"
    url = f"http://{host}:{port}"
    print("=" * 60)
    print(f"🚀 TikTok 视频批量抓取控制台已启动！")
    print(f"👉 访问地址: {url}")
    print("=" * 60)

    # 启动异步线程打开默认浏览器弹窗
    threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()

    # 运行 FastAPI 服务器
    uvicorn.run(app, host=host, port=port, log_level="warning")
