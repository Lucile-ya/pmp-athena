# Bridge health monitor — loops forever, emits one line per check
while ($true) {
    $found = $false
    $pid = 0
    try {
        foreach ($p in Get-Process -Name "node" -ErrorAction SilentlyContinue) {
            try {
                $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
                if ($cmd -match 'dist[/\\]main\.js\s+start') { $found = $true; $pid = $p.Id; break }
            } catch { }
        }
    } catch { }

    if ($found) {
        Write-Output "$(Get-Date -Format 'HH:mm:ss') [OK] Alive PID $pid"
    } else {
        Write-Output "$(Get-Date -Format 'HH:mm:ss') [DEAD] guard triggered"
        powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\pmp-athena\bridge_guard.ps1"
        Start-Sleep -Seconds 5
        foreach ($p in (Get-Process -Name "node" -ErrorAction SilentlyContinue)) {
            try {
                $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
                if ($cmd -match 'dist[/\\]main\.js\s+start') { Write-Output "$(Get-Date -Format 'HH:mm:ss') ✅ Recovered PID $($p.Id)"; break }
            } catch { }
        }
    }
    Start-Sleep -Seconds 30
}
