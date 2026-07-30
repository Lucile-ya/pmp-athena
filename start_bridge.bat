@echo off
chcp 65001 >nul
REM ============================================
REM  启动 PMP Athena 微信桥接（单实例）
REM  heartbeat 已关闭，不启动定时推送
REM ============================================

cd /d %USERPROFILE%\.claude\skills\wechat-claude-code

echo.
echo [1/3] 停止 heartbeat 调度器...
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq node.exe" /fo list ^| findstr "PID"') do (
    wmic process where "ProcessId=%%p" get CommandLine 2>nul | findstr /i "heartbeat-scheduler" >nul
    if not errorlevel 1 taskkill /f /pid %%p >nul 2>nul
)

echo [2/3] 停止旧桥接进程...
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq node.exe" /fo list ^| findstr "PID"') do (
    wmic process where "ProcessId=%%p" get CommandLine 2>nul | findstr /i "wechat-claude-code.*main.js" >nul
    if not errorlevel 1 taskkill /f /pid %%p >nul 2>nul
)

echo [3/3] 启动桥接...
start "" /B node dist\main.js start

echo.
echo ============================
echo 微信桥接已启动（单实例）
echo 日志: %USERPROFILE%\.wechat-claude-code\logs\
echo ============================
