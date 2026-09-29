# TikTok 博主视频批量下载工具

一个基于 **CustomTkinter** 现代 UI 与 **yt-dlp** 核心的 TikTok 视频批量抓取工具，支持命令行 (CLI) 和图形界面 (GUI) 双模式。

---

## ✨ 核心特性

- 🖥️ **现代图形界面 (GUI)**：基于 CustomTkinter 深色主题设计，操作直观友好。
- ⚡ **多线程防卡死**：解析与下载任务运行在独立线程，界面随时响应并支持中途取消。
- 🌐 **代理支持**：支持 HTTP / SOCKS5 代理配置（解决国内网络无法直接访问 TikTok 的问题）。
- 📋 **仅解析模式**：一键预扫描博主的所有视频列表，导出生成 `_video_list.json` 元数据索引。
- 📁 **自动分类归档**：按博主独立子目录保存，自动跳过已存在的历史视频（断点续传）。
- 🎯 **灵活过滤**：支持数量上限、日期范围限制、限速限流、Cookies 登录权限获取。

---

## 🚀 启动方式

### 方式 1：双击一键运行（推荐）
在文件夹内直接双击运行：
👉 **[`启动GUI.bat`](file:///C:/Users/Administrator/.gemini/antigravity/scratch/tiktok-scraper/启动GUI.bat)**

### 方式 2：命令行启动 GUI
```bash
python gui.py
```

### 方式 3：纯命令行模式 (CLI)
```bash
# 下载指定博主所有视频
python tiktok_downloader.py charlidamelio

# 仅抓取最新 20 个视频
python tiktok_downloader.py charlidamelio --max 20

# 仅生成视频列表，不下载文件
python tiktok_downloader.py charlidamelio --list-only
```

---

## 📁 目录文件说明

- [`gui.py`](file:///C:/Users/Administrator/.gemini/antigravity/scratch/tiktok-scraper/gui.py)：图形界面核心代码
- [`tiktok_downloader.py`](file:///C:/Users/Administrator/.gemini/antigravity/scratch/tiktok-scraper/tiktok_downloader.py)：命令行抓取脚本
- [`启动GUI.bat`](file:///C:/Users/Administrator/.gemini/antigravity/scratch/tiktok-scraper/启动GUI.bat)：Windows 快速启动入口
- `downloads/`：默认视频存放根目录
