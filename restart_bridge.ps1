# Restart wechat bridge (single instance)
$BridgeDir = "C:\Users\gwhea\.claude\skills\wechat-claude-code"
$NodeExe   = "C:\nvm4w\nodejs\node.exe"
$DataDir   = "C:\Users\gwhea\.wechat-claude-code"

function Test-BridgeCommandLine([string]$Cmd) {
    if ([string]::IsNullOrWhiteSpace($Cmd)) { return $false }
    if ($Cmd -match 'heartbeat-scheduler') { return $false }
    return ($Cmd -match 'dist[/\\]main\.js\s+start') -or ($Cmd -match 'wechat-claude-code.*main\.js')
}

Write-Host "[1/4] Stop old bridge..."
Get-CimInstance Win32_Process -Filter "name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { Test-BridgeCommandLine $_.CommandLine } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$lockFile = Join-Path $DataDir "bridge.pid"
if (Test-Path $lockFile) { Remove-Item $lockFile -Force -ErrorAction SilentlyContinue }

Write-Host "[2/4] npm run build..."
Push-Location $BridgeDir
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }
Pop-Location

Write-Host "[3/4] Start bridge..."
Start-Process -FilePath $NodeExe -ArgumentList "dist\main.js","start" -WorkingDirectory $BridgeDir -WindowStyle Hidden
Start-Sleep 2

$count = @(Get-CimInstance Win32_Process -Filter "name='node.exe'" -ErrorAction SilentlyContinue | Where-Object { Test-BridgeCommandLine $_.CommandLine }).Count
Write-Host "[4/4] Bridge instances: $count (expect 1)"
Write-Host "Done. Logs: $DataDir\logs\"
