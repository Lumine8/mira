# Start Mira natively - no Docker. One command: schema + API + (optionally) the
# desktop companion.
#
#   powershell -ExecutionPolicy Bypass -File scripts/start_native.ps1
#
# What it does:
#   * Boots the FastAPI backend with the repo .env, overriding the docker-only
#     values (OLLAMA_HOST, database) so it runs against the local Ollama and a
#     sqlite file (data/mira.db) - no Postgres, no container network.
#   * The backend serves the built web app AND the API on one port (8000), so
#     the desktop companion just points at it.
#   * Optionally launches the desktop app (installed Mira.exe, else npm start).
#
# Stop it with: Stop-Process -Id (Get-Content data/mira-api.pid)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$PidFile = Join-Path $Root "data\mira-api.pid"

# ---- environment ------------------------------------------------------------

# Load the repo .env (shared token, model names, keys) into the child process.
if (Test-Path (Join-Path $Root ".env")) {
    $loaded = 0
    Get-Content (Join-Path $Root ".env") | ForEach-Object {
        $t = $_.Trim()
        if ($t -and -not $t.StartsWith("#") -and $t -match "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim('"'), "Process")
            $loaded++
        }
    }
    Write-Host "loaded $loaded vars from .env" -ForegroundColor DarkGray
}

# Native overrides: no docker gateway, no postgres.
$env:OLLAMA_HOST = "http://localhost:11434"
$env:DATABASE_URL_OVERRIDE = "sqlite:///$($Root -replace '\\','/')/data/mira.db"

# ---- schema ------------------------------------------------------------------

$DataDir = Join-Path $Root "data"
if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir | Out-Null }

$Python = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "backend venv missing: $Python (run backend setup first)" }

# ---- speech model -------------------------------------------------------------

# The sherpa whisper model for local voice (STT). Downloaded once (~200MB) to
# data/models/sherpa; skip with -n when voice isn't needed.
$WhisperDir = Join-Path $DataDir "models\sherpa"
$WhisperModel = Join-Path $WhisperDir "sherpa-onnx-whisper-base.en"
$modelNeeded = $args[0] -ne "-n" -and $args[0] -ne "--no-desktop"
if ($modelNeeded -and -not (Test-Path (Join-Path $WhisperModel "base.en-encoder.int8.onnx"))) {
    Write-Host "downloading sherpa whisper base.en (~200MB, one-time)..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $WhisperDir -Force | Out-Null
    $tarball = Join-Path $env:TEMP "sherpa-onnx-whisper-base.en.tar.bz2"
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -UseBasicParsing `
        -Uri "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-base.en.tar.bz2" `
        -OutFile $tarball -TimeoutSec 600
    & $Python -c "import tarfile; tarfile.open(r'$tarball', 'r:bz2').extractall(r'$WhisperDir')"
    Remove-Item $tarball -ErrorAction SilentlyContinue
    Write-Host "whisper model ready" -ForegroundColor Green
}

Write-Host "native backend on http://127.0.0.1:8000 (sqlite + local ollama)" -ForegroundColor Cyan
Write-Host "  api + web:   http://127.0.0.1:8000/" -ForegroundColor DarkGray
Write-Host "  docs:        http://127.0.0.1:8000/docs" -ForegroundColor DarkGray

# ---- boot the api ------------------------------------------------------------

# kill a previous native instance
if (Test-Path $PidFile) {
    $old = Get-Content $PidFile
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
        Stop-Process -Id $old -Force
        Write-Host "stopped previous native api (pid $old)" -ForegroundColor DarkGray
    }
}

$proc = Start-Process -FilePath $Python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $Backend -WindowStyle Hidden -PassThru
$proc.Id | Set-Content $PidFile
Write-Host "api starting (pid $($proc.Id))..." -ForegroundColor DarkGray

# wait for health
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) { throw "api did not come up in time - check data/mira-api.log" }
Write-Host "api up: http://127.0.0.1:8000/" -ForegroundColor Green

# ---- desktop companion ---------------------------------------------------------

$launchDesktop = $args[0] -ne "-n" -and $args[0] -ne "--no-desktop"
if ($launchDesktop) {
    $desktopDir = Join-Path $Root "desktop"
    $installed = Join-Path $desktopDir "dist\win-unpacked\Mira.exe"
    if (Test-Path $installed) {
        Write-Host "launching Mira..." -ForegroundColor DarkGray
        Start-Process -FilePath $installed
    } elseif (Test-Path (Join-Path $desktopDir "node_modules\electron\dist\electron.exe")) {
        Write-Host "launching Mira (dev electron)..." -ForegroundColor DarkGray
        Start-Process -FilePath (Join-Path $desktopDir "node_modules\electron\dist\electron.exe") `
            -ArgumentList $desktopDir -WorkingDirectory $desktopDir
    } else {
        Write-Host "desktop build not found - skip with scripts/start_native.ps1 -n" -ForegroundColor Yellow
    }
} else {
    Write-Host "desktop skipped (-n)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Mira is home. Stop with: Stop-Process -Id (Get-Content data\mira-api.pid)" -ForegroundColor Cyan