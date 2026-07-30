<#
.SYNOPSIS
    PMP Athena — WeChat Bridge Watchdog
    - 每 60 秒检测桥接进程（单实例）
    - src 比 dist 新 → 自动 npm run build + 重启桥接
    - 进程挂了 → 编译后自动拉起
    不启动 heartbeat（已关闭）。
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile   = Join-Path $ScriptDir "watchdog.log"
$BridgeDir = "C:\Users\gwhea\.claude\skills\wechat-claude-code"
$NodeExe   = "C:\nvm4w\nodejs\node.exe"
$BridgeJs  = Join-Path $BridgeDir "dist\main.js"
$SrcDir    = Join-Path $BridgeDir "src"

function Write-WatchLog([string]$Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[${ts}] $Message" | Out-File -Append -FilePath $LogFile -Encoding utf8
}

function Test-BridgeCommandLine([string]$Cmd) {
    if ([string]::IsNullOrWhiteSpace($Cmd)) { return $false }
    if ($Cmd -match 'heartbeat-scheduler') { return $false }
    # 实际命令行为: node dist\main.js start（不含 wechat-claude-code 路径）
    return ($Cmd -match 'dist[/\\]main\.js\s+start') -or ($Cmd -match 'wechat-claude-code.*main\.js')
}

function Get-BridgeProcesses {
    $result = @()
    foreach ($p in (Get-Process -Name "node" -ErrorAction SilentlyContinue)) {
        try {
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
            if (Test-BridgeCommandLine $cmd) {
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
                Write-WatchLog "[OK] Stopped heartbeat PID $($p.Id)"
            }
        } catch { }
    }
}

function Stop-AllBridgeProcesses {
    foreach ($b in (Get-BridgeProcesses)) {
        Stop-Process -Id $b.Id -Force -ErrorAction SilentlyContinue
        Write-WatchLog "[OK] Stopped bridge PID $($b.Id)"
    }
}

function Test-BridgeSourceNewer {
    if (-not (Test-Path $BridgeJs)) { return $true }
    $distTime = (Get-Item $BridgeJs).LastWriteTime
    if (-not (Test-Path $SrcDir)) { return $false }
    $newestSrc = Get-ChildItem -Path $SrcDir -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $newestSrc) { return $false }
    return $newestSrc.LastWriteTime -gt $distTime
}

function Invoke-BridgeBuild {
    Write-WatchLog "[BUILD] npm run build ..."
    Push-Location $BridgeDir
    try {
        $output = & npm run build 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            Write-WatchLog "[ERROR] npm run build failed: $output"
            return $false
        }
        Write-WatchLog "[OK] npm run build succeeded"
        return $true
    } finally {
        Pop-Location
    }
}

function Start-BridgeProcess {
    # 启动前清掉重复实例，确保只留一个
    $existing = @(Get-BridgeProcesses | Sort-Object StartTime)
    if ($existing.Count -gt 1) {
        foreach ($b in ($existing | Select-Object -SkipLast 1)) {
            Stop-Process -Id $b.Id -Force -ErrorAction SilentlyContinue
            Write-WatchLog "[WARN] Killed duplicate bridge PID $($b.Id) before start"
        }
        return $existing[-1]
    }
    if ($existing.Count -eq 1) {
        Write-WatchLog "[OK] Bridge already running (PID $($existing[0].Id)), skip start"
        return $existing[0]
    }
    $proc = Start-Process -FilePath $NodeExe `
        -ArgumentList "`"$BridgeJs`" start" `
        -WorkingDirectory $BridgeDir `
        -WindowStyle Hidden `
        -PassThru
    Write-WatchLog "[OK] Bridge started (PID: $($proc.Id))"
    return $proc
}

Write-WatchLog "Watchdog started (auto-rebuild enabled, heartbeat disabled)"

while ($true) {
    Stop-HeartbeatProcesses

    $needsRebuild = Test-BridgeSourceNewer
    $bridges = @(Get-BridgeProcesses | Sort-Object StartTime)

    # 多实例：只保留最新一个
    if ($bridges.Count -gt 1) {
        $keep = $bridges[-1]
        foreach ($b in ($bridges | Select-Object -SkipLast 1)) {
            Stop-Process -Id $b.Id -Force -ErrorAction SilentlyContinue
            Write-WatchLog "[WARN] Killed duplicate bridge PID $($b.Id), keeping $($keep.Id)"
        }
        $bridges = @( $keep )
    }

    # 源码有更新 → 编译 + 重启
    if ($needsRebuild) {
        Write-WatchLog "[RELOAD] Bridge source newer than dist, rebuilding..."
        if (Invoke-BridgeBuild) {
            Stop-AllBridgeProcesses
            Start-Sleep -Seconds 1
            Start-BridgeProcess | Out-Null
        }
    }
    elseif ($bridges.Count -eq 0) {
        Write-WatchLog "[WARN] Bridge NOT running, building and starting..."
        Invoke-BridgeBuild | Out-Null
        Start-Sleep -Seconds 1
        Start-BridgeProcess | Out-Null
    }

    Start-Sleep -Seconds 60
}
