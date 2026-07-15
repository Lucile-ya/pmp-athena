@echo off
REM ============================================
REM  启动 PMP Athena 微信桥接守护进程
REM ============================================

cd /d %USERPROFILE%\.claude\skills\wechat-claude-code

echo.
echo [1/2] 杀掉旧进程...
taskkill /f /im node.exe /fi "WINDOWTITLE eq *wechat*" 2>nul
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq node.exe" /fo list ^| findstr "PID"') do (
    wmic process %%p get commandline 2>nul | findstr "main.js start" >nul
    if not errorlevel 1 taskkill /f /pid %%p >nul 2>nul
)

echo [2/2] 启动守护进程...
node dist/main.js start

echo.
echo ============================
echo 微信桥接已启动！
echo 日志: %USERPROFILE%\.wechat-claude-code\logs\
echo ============================
