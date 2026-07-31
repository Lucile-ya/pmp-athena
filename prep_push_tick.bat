@echo off
chcp 65001 >nul
REM PMP Athena — 备考推送调度（Task Scheduler 每分钟或每天 8:00 调用）
cd /d %~dp0
d:\miniconda\python.exe pmp_athena\prep_push.py tick >> pmp_notes\prep_push.log 2>&1
