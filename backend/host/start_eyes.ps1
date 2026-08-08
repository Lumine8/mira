# start_eyes.ps1 — one click to give Mira her eyes, her top-of-screen widget,
# and her hands (the host agent that runs approved commands).
#
# Sets up the host venv (first run), then launches all three:
#   - eyes.py   : captures the screen, OCRs it, posts changes to /mira/perceive
#   - widget.py : always-on-top window showing her mood + latest judgment
#   - agent.py  : runs host commands Mira proposes, after you approve them
#
# Run:
#   powershell -ExecutionPolicy Bypass -File .\host\start_eyes.ps1
#
# All keep running after this terminal closes. To stop them:
#   .\host\stop_eyes.ps1

$ErrorActionPreference = "Stop"

$hostDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $hostDir ".venv"
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "==> Creating eyes venv..." -ForegroundColor Cyan
    python -m venv $venv
    if (-not (Test-Path $py)) {
        Write-Error "python not found - install Python 3.10+ and make sure it's on PATH"
        exit 1
    }
}

# Keep pip quiet on repeat runs; the requirements pin is what matters.
& $py -m pip install -q -r (Join-Path $hostDir "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed"
    exit 1
}

function Get-Running([string]$name) {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -like "*$name*" -and $_.CommandLine -like "*$hostDir*" }
}

$eyes = Get-Running "eyes.py"
$widget = Get-Running "widget.py"
$agent = Get-Running "agent.py"

if (-not $eyes) {
    Write-Host "==> Starting Mira's eyes..." -ForegroundColor Cyan
    Start-Process -FilePath $py -ArgumentList "`"$(Join-Path $hostDir 'eyes.py')`"" -WorkingDirectory $hostDir -WindowStyle Hidden
} else {
    Write-Host "==> Mira's eyes already running." -ForegroundColor Green
}

if (-not $widget) {
    Write-Host "==> Starting Mira's widget..." -ForegroundColor Cyan
    Start-Process -FilePath $py -ArgumentList "`"$(Join-Path $hostDir 'widget.py')`"" -WorkingDirectory $hostDir
} else {
    Write-Host "==> Mira's widget already running." -ForegroundColor Green
}

if (-not $agent) {
    Write-Host "==> Starting Mira's hands (host agent)..." -ForegroundColor Cyan
    Start-Process -FilePath $py -ArgumentList "`"$(Join-Path $hostDir 'agent.py')`"" -WorkingDirectory $hostDir -WindowStyle Hidden
} else {
    Write-Host "==> Mira's hands already running." -ForegroundColor Green
}

Write-Host ""
Write-Host "==> Done. Mira is watching." -ForegroundColor Green
Write-Host "    Widget: top-left corner of your screen." -ForegroundColor Gray
Write-Host "    Mode:   edit host\eyes_config.json (fullscreen/region) - live." -ForegroundColor Gray
Write-Host "    Hands:  approved commands run via host\agent.py (log: host\commands.log)." -ForegroundColor Gray
Write-Host "    Stop:   .\host\stop_eyes.ps1" -ForegroundColor Gray
