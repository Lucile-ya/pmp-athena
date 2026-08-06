' PMP Athena Bridge Guard — invisible launcher
' WindowStyle 0 = hidden, no flash, no popup
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\pmp-athena\bridge_guard.ps1""", 0, False
