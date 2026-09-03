# PMP Athena - Register daily 08:00 WeChat push task
# Usage: powershell -ExecutionPolicy Bypass -File D:\pmp-athena\scripts\install_prep_push_task.ps1

$ErrorActionPreference = "Stop"
$TaskName = "PMP Athena Morning Push"
$RepoRoot = Split-Path $PSScriptRoot -Parent
$BatPath = Join-Path $RepoRoot "prep_push_tick.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "Batch file not found: $BatPath"
}

$Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At "08:00"
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "PMP Athena daily study plan and cheatsheet push" -Force | Out-Null

Write-Host "OK: Scheduled task registered: $TaskName"
Write-Host "Time: daily 08:00"
Write-Host "Script: $BatPath"
Write-Host ""
Write-Host "Test now:"
Write-Host "  d:\miniconda\python.exe pmp_athena\prep_push.py force-tick"
Write-Host "  d:\miniconda\python.exe pmp_athena\prep_push.py deliver"
