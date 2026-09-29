#!/usr/bin/env python3
"""
TikTok 博主视频批量下载脚本
使用 yt-dlp 抓取指定博主的所有视频
"""

import os
import sys
import json
import argparse
from datetime import datetime
import yt_dlp


def get_output_dir(username: str, base_dir: str = "downloads") -> str:
    """创建输出目录"""
    output_dir = os.path.join(base_dir, username)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def build_ydl_opts(output_dir: str, options: dict) -> dict:
    """构建 yt-dlp 配置选项"""
    outtmpl = os.path.join(output_dir, "%(upload_date)s_%(title).50s_%(id)s.%(ext)s")

    ydl_opts = {
        # 输出模板
        "outtmpl": outtmpl,
        # 视频质量：最佳画质
        "format": options.get("format", "bestvideo+bestaudio/best"),
        # 写入元数据
        "writethumbnail": options.get("save_thumbnail", True),
        "writeinfojson": options.get("save_info", True),
        "writedescription": False,
        # 跳过已下载的视频
        "ignoreerrors": True,
        "no_warnings": False,
        # 限速（避免被封）
        "ratelimit": options.get("rate_limit", None),
        # 重试次数
        "retries": 5,
        "fragment_retries": 5,
        # 并发下载数
        "concurrent_fragment_downloads": 4,
        # 进度显示
        "progress_hooks": [progress_hook],
        # User-Agent 伪装
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
        # Cookies（可选，用于访问私密内容）
        "cookiefile": options.get("cookiefile", None),
        # 下载数量限制
        "playlistend": options.get("max_videos", None),
        # 日期过滤
        "dateafter": options.get("date_after", None),
        "datebefore": options.get("date_before", None),
    }

    # 移除 None 值
    ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}
    return ydl_opts


# 全局进度统计
stats = {"downloaded": 0, "skipped": 0, "failed": 0}


def progress_hook(d: dict):
    """下载进度回调"""
    if d["status"] == "finished":
        stats["downloaded"] += 1
        filename = os.path.basename(d["filename"])
        print(f"\n  ✅ 下载完成: {filename}")
    elif d["status"] == "downloading":
        percent = d.get("_percent_str", "N/A").strip()
        speed = d.get("_speed_str", "N/A").strip()
        eta = d.get("_eta_str", "N/A").strip()
        print(f"\r  ⬇️  {percent}  速度: {speed}  剩余: {eta}    ", end="", flush=True)
    elif d["status"] == "error":
        stats["failed"] += 1


def fetch_video_list(url: str, ydl_opts: dict) -> list:
    """仅获取视频列表，不下载"""
    list_opts = ydl_opts.copy()
    list_opts["extract_flat"] = True
    list_opts["quiet"] = True
    list_opts.pop("progress_hooks", None)

    print("📋 正在获取视频列表...")
    with yt_dlp.YoutubeDL(list_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        return []

    entries = info.get("entries", [info])
    return [e for e in entries if e]


def save_video_list(entries: list, output_dir: str):
    """保存视频列表到 JSON 文件"""
    list_file = os.path.join(output_dir, "_video_list.json")
    data = {
        "fetched_at": datetime.now().isoformat(),
        "total": len(entries),
        "videos": [
            {
                "id": e.get("id"),
                "title": e.get("title"),
                "url": e.get("url") or e.get("webpage_url"),
                "upload_date": e.get("upload_date"),
                "duration": e.get("duration"),
                "view_count": e.get("view_count"),
            }
            for e in entries
        ],
    }
    with open(list_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"📄 视频列表已保存: {list_file}")


def download_videos(url: str, ydl_opts: dict):
    """执行批量下载"""
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def print_summary(username: str, output_dir: str):
    """打印下载总结"""
    print("\n" + "=" * 50)
    print(f"🎉 下载完成！博主: @{username}")
    print(f"   ✅ 成功: {stats['downloaded']} 个")
    print(f"   ⏭️  跳过: {stats['skipped']} 个（已存在）")
    print(f"   ❌ 失败: {stats['failed']} 个")
    print(f"   📁 保存目录: {os.path.abspath(output_dir)}")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="TikTok 博主视频批量下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python tiktok_downloader.py charlidamelio
  python tiktok_downloader.py charlidamelio --max 50
  python tiktok_downloader.py charlidamelio --list-only
  python tiktok_downloader.py charlidamelio --cookies cookies.txt --date-after 20240101
        """,
    )

    parser.add_argument("username", help="TikTok 博主用户名（不含 @）")
    parser.add_argument("-o", "--output", default="downloads", help="下载根目录（默认: downloads）")
    parser.add_argument("-m", "--max", type=int, help="最多下载视频数量")
    parser.add_argument("-f", "--format", default="bestvideo+bestaudio/best", help="视频格式")
    parser.add_argument("-c", "--cookies", help="cookies.txt 文件路径（用于登录状态）")
    parser.add_argument("-r", "--rate-limit", help="限速，例如: 1M（每秒 1MB）")
    parser.add_argument("--date-after", help="只下载此日期之后的视频，格式: YYYYMMDD")
    parser.add_argument("--date-before", help="只下载此日期之前的视频，格式: YYYYMMDD")
    parser.add_argument("--list-only", action="store_true", help="仅获取视频列表，不下载")
    parser.add_argument("--no-thumbnail", action="store_true", help="不保存封面图")
    parser.add_argument("--no-info", action="store_true", help="不保存 JSON 信息")

    args = parser.parse_args()
    username = args.username.lstrip("@")

    # TikTok 用户主页 URL
    url = f"https://www.tiktok.com/@{username}"
    print(f"\n🎵 TikTok 批量下载器")
    print(f"👤 博主: @{username}")
    print(f"🔗 URL: {url}\n")

    # 创建输出目录
    output_dir = get_output_dir(username, args.output)

    # 构建选项
    options = {
        "format": args.format,
        "save_thumbnail": not args.no_thumbnail,
        "save_info": not args.no_info,
        "cookiefile": args.cookies,
        "max_videos": args.max,
        "date_after": args.date_after,
        "date_before": args.date_before,
        "rate_limit": args.rate_limit,
    }

    ydl_opts = build_ydl_opts(output_dir, options)

    if args.list_only:
        # 仅获取列表
        entries = fetch_video_list(url, ydl_opts)
        if entries:
            print(f"🎬 共找到 {len(entries)} 个视频")
            save_video_list(entries, output_dir)
            for i, e in enumerate(entries[:10], 1):
                title = e.get("title", "未知标题")[:60]
                date = e.get("upload_date", "未知日期")
                print(f"  {i:3d}. [{date}] {title}")
            if len(entries) > 10:
                print(f"  ... 还有 {len(entries) - 10} 个视频（见 _video_list.json）")
        else:
            print("❌ 未找到视频，请检查用户名是否正确")
        return

    # 开始下载
    print(f"🚀 开始下载，保存到: {os.path.abspath(output_dir)}")
    if args.max:
        print(f"⚙️  限制下载数量: 最多 {args.max} 个")
    print("-" * 50)

    try:
        download_videos(url, ydl_opts)
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断下载")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")

    print_summary(username, output_dir)


if __name__ == "__main__":
    main()
