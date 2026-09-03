@echo off
chcp 65001 >nul
REM PMP Athena — 备考推送：生成队列 + 发送到微信（Task Scheduler 每天 08:00 调用）
cd /d %~dp0
d:\miniconda\python.exe pmp_athena\prep_push.py tick >> pmp_notes\prep_push.log 2>&1
d:\miniconda\python.exe pmp_athena\prep_push.py deliver >> pmp_notes\prep_push.log 2>&1
