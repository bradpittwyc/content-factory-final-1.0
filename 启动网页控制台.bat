@echo off
chcp 65001 >nul
title TikTok Web 批量抓取控制台
echo ========================================================
echo 正在启动 TikTok 批量抓取 Web 控制台...
echo 浏览器即将自动弹出: http://127.0.0.1:8000
echo ========================================================
python "%~dp0web_app.py"
pause
