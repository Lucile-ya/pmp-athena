@echo off
chcp 65001 >nul

REM ============================================
REM  PMP Athena — WeChat Bridge Watchdog
REM  每分钟检测 wechat-claude-code 进程
REM  挂了自动拉起，日志写入 watchdog.log
REM ============================================

cd /d %~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0watchdog.ps1"
