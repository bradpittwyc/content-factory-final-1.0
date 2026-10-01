#!/usr/bin/env python3
"""
TikTok 视频批量下载工具 - 图形界面 (GUI)
基于 CustomTkinter + yt-dlp 开发
"""

import os
import sys
import json
import re
import queue
import threading
import subprocess
from datetime import datetime
import customtkinter as ctk
from tkinter import filedialog, messagebox
import yt_dlp

# 设置外观模式和默认主题
ctk.set_appearance_mode("Dark")  # "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # "blue", "green", "dark-blue"


class TikTokDownloaderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("TikTok 视频批量抓取下载器")
        self.geometry("960, 720")
        self.minsize(850, 620)

        # 状态控制
        self.is_running = False
        self.stop_requested = False
        self.log_queue = queue.Queue()
        self.current_ydl = None

        # 构建界面布局
        self.create_widgets()
        self.check_queue()

    def create_widgets(self):
        # 顶部标题栏
        self.header_frame = ctk.CTkFrame(self, corner_radius=10)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 10))

        title_label = ctk.CTkLabel(
            self.header_frame,
            text="🎵 TikTok 视频批量抓取工具",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        title_label.pack(side="left", padx=15, pady=12)

        author_label = ctk.CTkLabel(
            self.header_frame,
            text="支持批量下载 / 列表分析 / 代理穿透 / 断点续传",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        author_label.pack(side="right", padx=15, pady=12)

        # 主配置区域
        self.config_frame = ctk.CTkFrame(self, corner_radius=10)
        self.config_frame.pack(fill="x", padx=15, pady=5)

        # 第一行: 用户名/URL
        row1 = ctk.CTkFrame(self.config_frame, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=(12, 6))

        user_label = ctk.CTkLabel(row1, text="博主用户名/链接:", width=110, anchor="w", font=ctk.CTkFont(weight="bold"))
        user_label.pack(side="left")

        self.entry_user = ctk.CTkEntry(
            row1,
            placeholder_text="例如: charlidamelio 或 @username 或 https://www.tiktok.com/@...",
            height=34
        )
        self.entry_user.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # 第二行: 保存路径
        row2 = ctk.CTkFrame(self.config_frame, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=6)

        dir_label = ctk.CTkLabel(row2, text="保存根目录:", width=110, anchor="w")
        dir_label.pack(side="left")

        default_download_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
        self.entry_dir = ctk.CTkEntry(row2, height=34)
        self.entry_dir.insert(0, default_download_dir)
        self.entry_dir.pack(side="left", fill="x", expand=True, padx=(5, 8))

        btn_browse_dir = ctk.CTkButton(row2, text="📁 浏览", width=80, height=34, command=self.browse_output_dir)
        btn_browse_dir.pack(side="right")

        # 第三行: 代理与数量限制
        row3 = ctk.CTkFrame(self.config_frame, fg_color="transparent")
        row3.pack(fill="x", padx=15, pady=6)

        proxy_label = ctk.CTkLabel(row3, text="网络代理(必选):", width=110, anchor="w")
        proxy_label.pack(side="left")

        self.entry_proxy = ctk.CTkEntry(
            row3,
            placeholder_text="国内必填! 如: http://127.0.0.1:7890 或 socks5://127.0.0.1:10808",
            height=34
        )
        self.entry_proxy.pack(side="left", fill="x", expand=True, padx=(5, 15))

        limit_label = ctk.CTkLabel(row3, text="下载数量上限:", anchor="w")
        limit_label.pack(side="left")

        self.entry_max = ctk.CTkEntry(row3, placeholder_text="留空则抓全部", width=110, height=34)
        self.entry_max.pack(side="left", padx=(8, 0))

        # 第四行: 高级筛选 (Cookies, 日期, 限速)
        row4 = ctk.CTkFrame(self.config_frame, fg_color="transparent")
        row4.pack(fill="x", padx=15, pady=6)

        cookies_label = ctk.CTkLabel(row4, text="Cookies 文件:", width=110, anchor="w")
        cookies_label.pack(side="left")

        self.entry_cookies = ctk.CTkEntry(row4, placeholder_text="cookies.txt (选填，访问私密或受限内容)", height=34)
        self.entry_cookies.pack(side="left", fill="x", expand=True, padx=(5, 8))

        btn_browse_cookies = ctk.CTkButton(row4, text="📄 选择", width=80, height=34, command=self.browse_cookies_file)
        btn_browse_cookies.pack(side="right")

        # 第五行: 日期与限速选项
        row5 = ctk.CTkFrame(self.config_frame, fg_color="transparent")
        row5.pack(fill="x", padx=15, pady=6)

        date_label = ctk.CTkLabel(row5, text="起始日期 (YYYYMMDD):", width=140, anchor="w")
        date_label.pack(side="left")

        self.entry_date_after = ctk.CTkEntry(row5, placeholder_text="例: 20240101", width=110, height=32)
        self.entry_date_after.pack(side="left", padx=(0, 20))

        rate_label = ctk.CTkLabel(row5, text="下载限速:", anchor="w")
        rate_label.pack(side="left")

        self.entry_rate = ctk.CTkEntry(row5, placeholder_text="例: 2M (留空不限)", width=120, height=32)
        self.entry_rate.pack(side="left", padx=(8, 20))

        # 复选框选项
        self.var_thumb = ctk.BooleanVar(value=True)
        self.chk_thumb = ctk.CTkCheckBox(row5, text="保存视频封面", variable=self.var_thumb)
        self.chk_thumb.pack(side="left", padx=(0, 15))

        self.var_info = ctk.BooleanVar(value=True)
        self.chk_info = ctk.CTkCheckBox(row5, text="保存视频元数据JSON", variable=self.var_info)
        self.chk_info.pack(side="left")

        # 操作按钮栏
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.action_frame.pack(fill="x", padx=15, pady=10)

        self.btn_list = ctk.CTkButton(
            self.action_frame,
            text="📋 仅解析视频列表",
            width=150,
            height=38,
            fg_color="#3B82F6",
            hover_color="#2563EB",
            command=self.start_list_only
        )
        self.btn_list.pack(side="left", padx=(0, 10))

        self.btn_download = ctk.CTkButton(
            self.action_frame,
            text="🚀 开始批量下载",
            width=160,
            height=38,
            fg_color="#10B981",
            hover_color="#059669",
            command=self.start_download
        )
        self.btn_download.pack(side="left", padx=(0, 10))

        self.btn_stop = ctk.CTkButton(
            self.action_frame,
            text="⏹ 停止任务",
            width=110,
            height=38,
            fg_color="#EF4444",
            hover_color="#DC2626",
            state="disabled",
            command=self.stop_task
        )
        self.btn_stop.pack(side="left", padx=(0, 10))

        self.btn_open_folder = ctk.CTkButton(
            self.action_frame,
            text="📂 打开下载目录",
            width=130,
            height=38,
            fg_color="#4B5563",
            hover_color="#374151",
            command=self.open_output_folder
        )
        self.btn_open_folder.pack(side="left", padx=(0, 10))

        self.btn_tonguetwister = ctk.CTkButton(
            self.action_frame,
            text="🗣️ 绕口令生成卡片",
            width=140,
            height=38,
            fg_color="#8B5CF6",
            hover_color="#7C3AED",
            command=self.open_tonguetwister_dialog
        )
        self.btn_tonguetwister.pack(side="left")

        self.lbl_status = ctk.CTkLabel(
            self.action_frame,
            text="就绪",
            font=ctk.CTkFont(size=13),
            anchor="e"
        )
        self.lbl_status.pack(side="right", padx=5)

        # 进度条
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=15, pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=12)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x")

        # 日志输出区域
        self.log_frame = ctk.CTkFrame(self, corner_radius=10)
        self.log_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        log_title_row = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        log_title_row.pack(fill="x", padx=12, pady=(8, 4))

        log_title = ctk.CTkLabel(log_title_row, text="运行日志与监控:", font=ctk.CTkFont(weight="bold"))
        log_title.pack(side="left")

        btn_clear = ctk.CTkButton(
            log_title_row,
            text="清空日志",
            width=70,
            height=24,
            fg_color="#374151",
            hover_color="#1F2937",
            command=self.clear_logs
        )
        btn_clear.pack(side="right")

        self.log_text = ctk.CTkTextbox(self.log_frame, wrap="word", font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def log(self, text: str):
        """线程安全的日志添加"""
        self.log_queue.put(("log", text))

    def update_status(self, text: str):
        """线程安全的状态更新"""
        self.log_queue.put(("status", text))

    def update_progress(self, percent: float):
        """更新进度条"""
        self.log_queue.put(("progress", percent))

    def check_queue(self):
        """定时处理消息队列并更新界面"""
        try:
            while True:
                msg_type, data = self.log_queue.get_nowait()
                if msg_type == "log":
                    self.log_text.insert("end", data + "\n")
                    self.log_text.see("end")
                elif msg_type == "status":
                    self.lbl_status.configure(text=data)
                elif msg_type == "progress":
                    self.progress_bar.set(max(0.0, min(1.0, data)))
                elif msg_type == "task_done":
                    self.on_task_finished()
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

    def browse_output_dir(self):
        selected = filedialog.askdirectory(initialdir=self.entry_dir.get())
        if selected:
            self.entry_dir.delete(0, "end")
            self.entry_dir.insert(0, selected)

    def browse_cookies_file(self):
        selected = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if selected:
            self.entry_cookies.delete(0, "end")
            self.entry_cookies.insert(0, selected)

    def open_output_folder(self):
        out_dir = self.entry_dir.get().strip()
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(out_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", out_dir])
        else:
            subprocess.Popen(["xdg-open", out_dir])

    def clear_logs(self):
        self.log_text.delete("1.0", "end")

    def parse_username_and_url(self, raw_input: str):
        """从用户输入中提取纯用户名与主页完整 URL"""
        text = raw_input.strip()
        if not text:
            return None, None

        # 匹配 URL: https://www.tiktok.com/@username...
        url_match = re.search(r"tiktok\.com/@([a-zA-Z0-9_\.\-]+)", text)
        if url_match:
            username = url_match.group(1)
        else:
            username = text.lstrip("@").strip().split("/")[0]

        target_url = f"https://www.tiktok.com/@{username}"
        return username, target_url

    def build_ydl_options(self, target_dir: str, list_only: bool = False):
        """构建 yt-dlp 配置字典"""
        proxy = self.entry_proxy.get().strip()
        cookies = self.entry_cookies.get().strip()
        max_videos = self.entry_max.get().strip()
        date_after = self.entry_date_after.get().strip()
        rate_limit = self.entry_rate.get().strip()

        ydl_opts = {
            "ignoreerrors": True,
            "no_warnings": False,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 4,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            }
        }

        # 代理设置
        if proxy:
            ydl_opts["proxy"] = proxy

        # Cookies
        if cookies and os.path.exists(cookies):
            ydl_opts["cookiefile"] = cookies

        # 数量限制
        if max_videos and max_videos.isdigit():
            ydl_opts["playlistend"] = int(max_videos)

        # 日期限制
        if date_after:
            ydl_opts["dateafter"] = date_after

        # 限速
        if rate_limit:
            ydl_opts["ratelimit"] = rate_limit

        if list_only:
            ydl_opts["extract_flat"] = True
            ydl_opts["quiet"] = True
        else:
            # 下载相关选项
            outtmpl = os.path.join(target_dir, "%(upload_date)s_%(title).50s_%(id)s.%(ext)s")
            ydl_opts["outtmpl"] = outtmpl
            ydl_opts["format"] = "bestvideo+bestaudio/best"
            ydl_opts["writethumbnail"] = self.var_thumb.get()
            ydl_opts["writeinfojson"] = self.var_info.get()
            ydl_opts["progress_hooks"] = [self.on_download_progress]

        return ydl_opts

    def on_download_progress(self, d):
        if self.stop_requested:
            raise Exception("用户主动中止下载任务")

        status = d.get("status")
        if status == "downloading":
            percent_str = d.get("_percent_str", "").strip()
            speed_str = d.get("_speed_str", "").strip()
            eta_str = d.get("_eta_str", "").strip()

            # 解析进度百分比
            clean_pct = re.sub(r"[^\d.]", "", percent_str)
            if clean_pct:
                try:
                    pct = float(clean_pct) / 100.0
                    self.update_progress(pct)
                except ValueError:
                    pass

            self.update_status(f"下载中: {percent_str} | 速度: {speed_str} | 剩余: {eta_str}")
        elif status == "finished":
            filename = os.path.basename(d.get("filename", ""))
            self.log(f"  ✅ 单个视频下载完成: {filename}")
            self.update_progress(1.0)
        elif status == "error":
            self.log(f"  ❌ 下载出错")

    def start_list_only(self):
        self.prepare_and_run(list_only=True)

    def start_download(self):
        self.prepare_and_run(list_only=False)

    def prepare_and_run(self, list_only: bool):
        raw_user = self.entry_user.get().strip()
        if not raw_user:
            messagebox.showwarning("提示", "请输入 TikTok 博主用户名或主页链接！")
            return

        username, target_url = self.parse_username_and_url(raw_user)
        if not username:
            messagebox.showerror("错误", "无法解析博主用户名，请检查输入格式。")
            return

        base_dir = self.entry_dir.get().strip()
        user_dir = os.path.join(base_dir, username)
        os.makedirs(user_dir, exist_ok=True)

        # 检查代理提示
        proxy = self.entry_proxy.get().strip()
        if not proxy:
            # 仅做软提示，不强行阻止
            self.log("⚠️ 注意: 未填写网络代理，如在国内网络环境下访问 TikTok 可能会超时或连接失败。")

        self.is_running = True
        self.stop_requested = False
        self.btn_download.configure(state="disabled")
        self.btn_list.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar.set(0)

        # 启动后台工作线程
        action_name = "解析列表" if list_only else "批量下载"
        self.log(f"\n{'='*20} 启动任务: {action_name} {'='*20}")
        self.log(f"👤 目标博主: @{username}")
        self.log(f"🔗 主页链接: {target_url}")
        self.log(f"📁 目标目录: {user_dir}")
        if proxy:
            self.log(f"🌐 使用代理: {proxy}")

        self.worker_thread = threading.Thread(
            target=self.run_worker,
            args=(username, target_url, user_dir, list_only),
            daemon=True
        )
        self.worker_thread.start()

    def run_worker(self, username: str, target_url: str, user_dir: str, list_only: bool):
        try:
            ydl_opts = self.build_ydl_options(user_dir, list_only=list_only)

            if list_only:
                self.update_status(f"正在扫描 @{username} 的视频列表...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    self.current_ydl = ydl
                    info = ydl.extract_info(target_url, download=False)

                if not info:
                    self.log("❌ 未能获取到任何视频信息，请检查网络/代理或用户名。")
                    return

                entries = info.get("entries", [info])
                valid_entries = [e for e in entries if e]
                total_count = len(valid_entries)
                self.log(f"🎉 扫描完成！共获取到 {total_count} 个视频条目。")

                # 保存为 JSON 列表
                list_file = os.path.join(user_dir, "_video_list.json")
                out_data = {
                    "author": username,
                    "fetched_at": datetime.now().isoformat(),
                    "total": total_count,
                    "videos": [
                        {
                            "id": e.get("id"),
                            "title": e.get("title", ""),
                            "url": e.get("url") or e.get("webpage_url", ""),
                            "upload_date": e.get("upload_date", ""),
                            "duration": e.get("duration", 0),
                            "view_count": e.get("view_count", 0)
                        }
                        for e in valid_entries
                    ]
                }
                with open(list_file, "w", encoding="utf-8") as f:
                    json.dump(out_data, f, ensure_ascii=False, indent=2)

                self.log(f"📄 列表索引已保存至: {list_file}")

                # 显示前 15 条
                self.log("\n--- 视频概览 (前15条) ---")
                for i, v in enumerate(valid_entries[:15], 1):
                    v_title = (v.get("title") or "无标题").replace("\n", " ")[:40]
                    v_date = v.get("upload_date", "未知日期")
                    self.log(f"  {i:2d}. [{v_date}] {v_title}")
                if total_count > 15:
                    self.log(f"  ... 还有 {total_count - 15} 个视频已记录在 JSON 文件中。")

            else:
                self.update_status(f"正在下载 @{username} 的视频...")
                self.log("🚀 开始连接并抓取视频资源...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    self.current_ydl = ydl
                    ydl.download([target_url])

                self.log(f"\n🎉 恭喜！任务执行完成！所有视频已保存至: {user_dir}")

        except Exception as e:
            err_msg = str(e)
            if "用户主动中止" in err_msg:
                self.log("⚠️ 任务已被用户手动停止。")
            else:
                self.log(f"❌ 运行异常: {err_msg}")
        finally:
            self.current_ydl = None
            self.log_queue.put(("task_done", None))

    def stop_task(self):
        if self.is_running:
            self.stop_requested = True
            self.log("⏹ 正在请求停止任务，请稍候...")
            self.update_status("正在停止...")
            self.btn_stop.configure(state="disabled")

    def on_task_finished(self):
        self.is_running = False
        self.stop_requested = False
        self.btn_download.configure(state="normal")
        self.btn_list.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.update_status("就绪 / 任务完成")

    def open_tonguetwister_dialog(self):
        """弹出 Tony 英语绕口令流水线生成窗口"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("🗣️ Tony 英语绕口令流水线卡片生成器")
        dialog.geometry("450x380")
        dialog.transient(self)

        lbl_title = ctk.CTkLabel(dialog, text="🗣️ 生成 Tony 绕口令训练卡片", font=ctk.CTkFont(size=18, weight="bold"))
        lbl_title.pack(pady=(15, 10))

        # 难度选择
        lbl_level = ctk.CTkLabel(dialog, text="选择难度等级 (初/中/高):", anchor="w")
        lbl_level.pack(fill="x", padx=25, pady=(5, 2))
        combo_level = ctk.CTkComboBox(dialog, values=["初级", "中级", "高级"])
        combo_level.set("初级")
        combo_level.pack(fill="x", padx=25, pady=(0, 10))

        # 目标音标
        lbl_sound = ctk.CTkLabel(dialog, text="目标发音/难音标 (可选):", anchor="w")
        lbl_sound.pack(fill="x", padx=25, pady=(5, 2))
        entry_sound = ctk.CTkEntry(dialog, placeholder_text="例如: /s/ vs /ʃ/ 或 /θ/ vs /s/")
        entry_sound.pack(fill="x", padx=25, pady=(0, 10))

        # 场景主题
        lbl_topic = ctk.CTkLabel(dialog, text="场景主题 (可选):", anchor="w")
        lbl_topic.pack(fill="x", padx=25, pady=(5, 2))
        entry_topic = ctk.CTkEntry(dialog, placeholder_text="例如: 日常生活、科技、海述等")
        entry_topic.pack(fill="x", padx=25, pady=(0, 15))

        def start_generate():
            level = combo_level.get()
            sound = entry_sound.get().strip() or "自由发音"
            topic = entry_topic.get().strip() or "日常口语"
            dialog.destroy()

            self.log(f"\n🚀 [绕口令流水线] 开始自动生成【{level}】发音卡片...")
            self.update_status(f"正在生成【{level}】绕口令卡片...")

            def worker():
                try:
                    import tony_tonguetwister_processor
                    item = tony_tonguetwister_processor.process_and_add_tonguetwister(level=level, target_sound=sound, topic=topic)
                    self.log(f"✅ 【{level}】绕口令卡片生成成功！")
                    self.log(f"   英文: {item.get('english_text')}")
                    self.log(f"   中文: {item.get('chinese_text')}")
                    self.log(f"   难点解析: {item.get('phonetic_tips')}")
                    if item.get("audio_url"):
                        self.log(f"   🎙️ 音频生成完成: {item.get('audio_url')}")
                except Exception as e:
                    self.log(f"❌ 绕口令生成失败: {e}")
                finally:
                    self.update_status("就绪")

            threading.Thread(target=worker, daemon=True).start()

        btn_run = ctk.CTkButton(
            dialog,
            text="✨ 立即生成并集成到内容工厂",
            fg_color="#8B5CF6",
            hover_color="#7C3AED",
            height=36,
            command=start_generate
        )
        btn_run.pack(fill="x", padx=25, pady=10)



if __name__ == "__main__":
    app = TikTokDownloaderGUI()
    app.mainloop()
