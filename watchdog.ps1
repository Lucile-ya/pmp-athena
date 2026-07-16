<#
.SYNOPSIS
    PMP Athena — WeChat Bridge Watchdog (PowerShell version)
    每 60 秒检测 wechat-claude-code 进程，挂了自动拉起
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile   = Join-Path $ScriptDir "watchdog.log"
$BridgeDir = "C:\Users\gwhea\.claude\skills\wechat-claude-code"
$NodeExe   = "C:\nvm4w\nodejs\node.exe"
$BridgeJs  = Join-Path $BridgeDir "dist\main.js"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[${timestamp}] Watchdog started (ps1)" | Out-File -Append -FilePath $LogFile -Encoding utf8

while ($true) {
    $found = $false
    try {
        $procs = Get-Process -Name "node" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            try {
                if ($p.CommandLine -like "*wechat-claude-code*") {
                    $found = $true
                    break
                }
            } catch {
                # Can't read CommandLine (access denied), skip this process
            }
        }
    } catch {
        # Get-Process itself failed
    }

    if (-not $found) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        "[${timestamp}] [WARN] Bridge NOT running, starting..." | Out-File -Append -FilePath $LogFile -Encoding utf8

        try {
            $proc = Start-Process -FilePath $NodeExe `
                -ArgumentList "`"$BridgeJs`" start" `
                -WorkingDirectory $BridgeDir `
                -WindowStyle Hidden `
                -PassThru

            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            "[${timestamp}] [OK] Bridge started (PID: $($proc.Id))" | Out-File -Append -FilePath $LogFile -Encoding utf8
        } catch {
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            "[${timestamp}] [ERROR] Failed to start bridge: $_" | Out-File -Append -FilePath $LogFile -Encoding utf8
        }
    }

    Start-Sleep -Seconds 60
}
