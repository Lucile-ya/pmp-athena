<#
.SYNOPSIS
    PMP Athena — WeChat Bridge Guard
    计划任务调用版本，每 5 分钟执行一次：
    - 桥接活着 → 静默退出
    - 桥接死了 → 清理残留锁 → 编译 → 拉起
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile   = Join-Path $ScriptDir "bridge_guard.log"
$BridgeDir = "C:\Users\gwhea\.claude\skills\wechat-claude-code"
$NodeExe   = "C:\nvm4w\nodejs\node.exe"
$BridgeJs  = Join-Path $BridgeDir "dist\main.js"
$LockFile  = "C:\Users\gwhea\.wechat-claude-code\bridge.pid"

function Write-GuardLog([string]$Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[${ts}] $Message" | Out-File -Append -FilePath $LogFile -Encoding utf8
}

function Test-BridgeCommandLine([string]$Cmd) {
    if ([string]::IsNullOrWhiteSpace($Cmd)) { return $false }
    if ($Cmd -match 'heartbeat-scheduler') { return $false }
    return ($Cmd -match 'dist[/\\]main\.js\s+start') -or ($Cmd -match 'wechat-claude-code.*main\.js')
}

function Get-BridgeProcess {
    foreach ($p in (Get-Process -Name "node" -ErrorAction SilentlyContinue)) {
        try {
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
            if ($cmd -and (Test-BridgeCommandLine $cmd)) {
                return $p
            }
        } catch { }
    }
    return $null
}

function Clear-StaleLock {
    if (-not (Test-Path $LockFile)) { return }
    try {
        $raw = Get-Content $LockFile -Raw
        $lockPid = [int]($raw.Trim())
        try {
            $proc = Get-Process -Id $lockPid -ErrorAction Stop
            # PID in lock is alive — check if it's actually a bridge
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)").CommandLine
            if ($cmd -and (Test-BridgeCommandLine $cmd)) {
                # Lock is valid, leave it
                return
            }
            # Different process with same PID, stale
            Write-GuardLog "[CLEAN] Stale lock (PID $lockPid is $($proc.ProcessName), not bridge)"
        } catch {
            Write-GuardLog "[CLEAN] Stale lock (PID $lockPid not found)"
        }
        Remove-Item $LockFile -Force
    } catch {
        Write-GuardLog "[CLEAN] Removed unreadable lock file"
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}

# ─── Main ──────────────────────────────────────────────────────────

# Step 1: Check if bridge is already running
$existing = Get-BridgeProcess
if ($existing) {
    # Bridge is running — nothing to do, exit silently
    exit 0
}

# Step 2: Bridge NOT running — take action
Write-GuardLog "[GUARD] Bridge is NOT running, starting recovery..."

# Step 2a: Clear any stale lock files
Clear-StaleLock

# Step 3: Build if dist is missing or source is newer
$needBuild = $false
if (-not (Test-Path $BridgeJs)) {
    $needBuild = $true
    Write-GuardLog "[BUILD] dist/main.js missing"
} else {
    $distTime = (Get-Item $BridgeJs).LastWriteTime
    $newestSrc = Get-ChildItem -Path (Join-Path $BridgeDir "src") -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newestSrc -and $newestSrc.LastWriteTime -gt $distTime) {
        $needBuild = $true
        Write-GuardLog "[BUILD] Source newer than dist"
    }
}

if ($needBuild) {
    Push-Location $BridgeDir
    try {
        $output = npm run build 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            Write-GuardLog "[ERROR] npm run build failed: $output"
            Pop-Location
            exit 1
        }
        Write-GuardLog "[OK] npm run build succeeded"
    } finally {
        Pop-Location
    }
}

# Step 4: Stop any orphan heartbeat processes
foreach ($p in (Get-Process -Name "node" -ErrorAction SilentlyContinue)) {
    try {
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
        if ($cmd -match 'heartbeat-scheduler') {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Write-GuardLog "[OK] Stopped orphan heartbeat PID $($p.Id)"
        }
    } catch { }
}

# Step 5: Start the bridge
Write-GuardLog "[START] Launching bridge..."
$proc = Start-Process -FilePath $NodeExe `
    -ArgumentList "dist\main.js start" `
    -WorkingDirectory $BridgeDir `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2

# Step 6: Verify it's alive
$verify = Get-BridgeProcess
if ($verify) {
    Write-GuardLog "[OK] Bridge started successfully (PID $($verify.Id))"
    exit 0
} else {
    Write-GuardLog "[ERROR] Bridge started but not detected — check stderr.log"
    exit 1
}
