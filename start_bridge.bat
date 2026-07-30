@echo off
chcp 65001 >nul
REM ============================================
REM  启动 PMP Athena 微信桥接（单实例）
REM  heartbeat 已关闭，不启动定时推送
REM ============================================

cd /d %USERPROFILE%\.claude\skills\wechat-claude-code

echo.
echo [1/4] 停止 heartbeat 调度器...
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq node.exe" /fo list ^| findstr "PID"') do (
    wmic process where "ProcessId=%%p" get CommandLine 2>nul | findstr /i "heartbeat-scheduler" >nul
    if not errorlevel 1 taskkill /f /pid %%p >nul 2>nul
)

echo [2/4] 编译 TypeScript（确保硬路由最新）...
call npm run build >nul 2>&1
if errorlevel 1 (
    echo [WARN] npm run build 失败，将使用已有 dist\
)

echo [3/4] 停止旧桥接进程...
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq node.exe" /fo list ^| findstr "PID"') do (
    wmic process where "ProcessId=%%p" get CommandLine 2>nul | findstr /i "dist\\main.js" | findstr /i "start" >nul
    if not errorlevel 1 taskkill /f /pid %%p >nul 2>nul
)
if exist "%USERPROFILE%\.wechat-claude-code\bridge.pid" del /f /q "%USERPROFILE%\.wechat-claude-code\bridge.pid" >nul 2>nul

echo [4/4] 启动桥接...
start "" /B node dist\main.js start

echo.
echo ============================
echo 微信桥接已启动（单实例）
echo 日志: %USERPROFILE%\.wechat-claude-code\logs\
echo ============================
