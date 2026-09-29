@echo off
chcp 65001 >nul
title TikTok 视频批量下载器
echo 正在启动 TikTok 批量抓取下载器 GUI 界面...
python "%~dp0gui.py"
if %errorlevel% neq 0 (
    echo.
    echo 程序退出或发生异常，请检查上方信息。
    pause
)
