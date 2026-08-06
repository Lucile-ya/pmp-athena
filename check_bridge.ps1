# Quick bridge health check — outputs JSON for shell consumption
$found = $false
try {
    foreach ($p in Get-Process -Name "node" -ErrorAction SilentlyContinue) {
        try {
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)").CommandLine
            if ($cmd -match 'dist[/\\]main\.js\s+start') { $found = $true; break }
        } catch { }
    }
} catch { }

if ($found) {
    $log = "C:\Users\gwhea\.wechat-claude-code\logs\bridge-$(Get-Date -Format 'yyyy-MM-dd').log"
    $lastLine = ""
    if (Test-Path $log) { $lastLine = Get-Content $log -Tail 1 }
    Write-Output "ALIVE|$($p.Id)|$lastLine"
} else {
    Write-Output "DEAD"
}
