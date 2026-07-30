<#
.SYNOPSIS
    PMP Athena — WeChat Bridge Watchdog
    每 60 秒检测桥接进程：确保仅 1 个实例，挂了自动拉起。
    不启动 heartbeat（已关闭）。
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile   = Join-Path $ScriptDir "watchdog.log"
$BridgeDir = "C:\Users\gwhea\.claude\skills\wechat-claude-code"
$NodeExe   = "C:\nvm4w\nodejs\node.exe"
$BridgeJs  = Join-Path $BridgeDir "dist\main.js"

function Get-BridgeProcesses {
    $result = @()
    foreach ($p in (Get-Process -Name "node" -ErrorAction SilentlyContinue)) {
        try {
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
            if ($cmd -match 'wechat-claude-code.*main\.js') {
                $result += [PSCustomObject]@{ Id = $p.Id; Cmd = $cmd; StartTime = $p.StartTime }
            }
        } catch { }
    }
    return $result
}

function Stop-HeartbeatProcesses {
    foreach ($p in (Get-Process -Name "node" -ErrorAction SilentlyContinue)) {
        try {
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
            if ($cmd -match 'heartbeat-scheduler') {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
                $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
                "[${ts}] [OK] Stopped heartbeat PID $($p.Id)" | Out-File -Append -FilePath $LogFile -Encoding utf8
            }
        } catch { }
    }
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[${timestamp}] Watchdog started (heartbeat disabled)" | Out-File -Append -FilePath $LogFile -Encoding utf8

while ($true) {
    Stop-HeartbeatProcesses

    $bridges = Get-BridgeProcesses | Sort-Object StartTime

    if ($bridges.Count -gt 1) {
        $keep = $bridges[-1]
        foreach ($b in ($bridges | Select-Object -SkipLast 1)) {
            Stop-Process -Id $b.Id -Force -ErrorAction SilentlyContinue
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            "[${timestamp}] [WARN] Killed duplicate bridge PID $($b.Id), keeping $($keep.Id)" | Out-File -Append -FilePath $LogFile -Encoding utf8
        }
        $bridges = @( $keep )
    }

    if ($bridges.Count -eq 0) {
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
