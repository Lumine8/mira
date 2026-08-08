# stop_eyes.ps1 — stops Mira's eyes, widget, and host agent launched by start_eyes.ps1.

$hostDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*$hostDir*" -and ($_.CommandLine -like "*eyes.py*" -or $_.CommandLine -like "*widget.py*" -or $_.CommandLine -like "*agent.py*") } |
    ForEach-Object {
        Write-Host "Stopping PID $($_.ProcessId): $($_.CommandLine)" -ForegroundColor Cyan
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Write-Host "==> Mira's eyes, widget, and host agent stopped." -ForegroundColor Green
