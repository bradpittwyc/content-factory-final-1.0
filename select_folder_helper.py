#!/usr/bin/env python3
import sys
import os
import tkinter as tk
from tkinter import filedialog

def pick_folder(initial_dir=""):
    try:
        root = tk.Tk()
        root.withdraw()
        # 强制窗口置顶并聚焦到最前面
        root.attributes('-topmost', True)
        root.focus_force()
        init = os.path.abspath(initial_dir) if (initial_dir and os.path.exists(initial_dir)) else os.getcwd()
        folder = filedialog.askdirectory(
            initialdir=init,
            title="请选择 TikTok 视频存储目录"
        )
        root.destroy()
        return folder or ""
    except Exception:
        return ""

if __name__ == "__main__":
    init = sys.argv[1] if len(sys.argv) > 1 else ""
    folder = pick_folder(init)
    if folder:
        sys.stdout.buffer.write(folder.encode("utf-8"))
