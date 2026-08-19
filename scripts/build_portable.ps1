# Build the portable Mira app: one folder (dist/mira-portable/) that contains the
# desktop companion, the backend, a self-contained Python runtime, the host agent,
# and (when available) Ollama with its models. The desktop companion supervises
# the whole stack, so installing the folder on any Windows PC = Mira running there.
#
#   powershell -ExecutionPolicy Bypass -File scripts/build_portable.ps1
#
# Switches:
#   -SkipDesktop  reuse an existing desktop build instead of running electron-builder
#   -SkipPython   keep an existing runtime/python instead of building it again
#   -SkipModels   skip downloading the sherpa whisper model into the bundle
#   -NoOllama     don't try to copy a local Ollama install into the bundle
#   -SkipInstall  assemble the portable folder but skip the NSIS installer
#
# The result layout (the desktop supervisor understands it):
#   dist/mira-portable/
#     Mira.exe, resources/...            electron app (owner + supervisor)
#     runtime/python/                    embeddable python + all backend deps
#     runtime/backend/                   backend source (app/, host/, .env)
#     runtime/ollama/                    ollama.exe + models/ (optional)
#     data/                              writable runtime state (db, models, logs)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Desktop = Join-Path $Root "desktop"
$Backend = Join-Path $Root "backend"
$Dist = Join-Path $Root "dist"
$Portable = Join-Path $Dist "mira-portable"
$Runtime = Join-Path $Portable "runtime"
$PyRuntime = Join-Path $Runtime "python"
$BackendRuntime = Join-Path $Runtime "backend"
$DataDir = Join-Path $Portable "data"
$Temp = Join-Path $env:TEMP "mira-build"
$PyVersion = "3.12.7"
$PyUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
$PyZip = Join-Path $Temp "python-$PyVersion-embed-amd64.zip"
$GetPip = Join-Path $Temp "get-pip.py"

$skipDesktop = $args -contains "-SkipDesktop"
$skipPython = $args -contains "-SkipPython"
$skipModels = $args -contains "-SkipModels"
$noOllama = $args -contains "-NoOllama"
$skipInstall = $args -contains "-SkipInstall"

function Step([string]$msg) { Write-Host "== $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "   $msg" -ForegroundColor DarkGray }

New-Item -ItemType Directory -Path $Temp -Force | Out-Null
New-Item -ItemType Directory -Path $Dist -Force | Out-Null

# ---- 1. electron app (owner) ---------------------------------------------------
Step "desktop companion"
$winUnpacked = Join-Path $Desktop "dist\win-unpacked"
if (-not $skipDesktop) {
    Push-Location $Desktop
    try { npm run build | Out-Host } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $winUnpacked "Mira.exe"))) {
    throw "desktop build missing: $winUnpacked\Mira.exe (remove -SkipDesktop)"
}
# Mirror the app contents into the portable root (robocopy /IS /IT refreshes
# changed electron files while leaving runtime/ and data/ alone). Always runs so
# a rebuilt app (new icon, changed renderer) replaces the stale copy.
robocopy $winUnpacked $Portable /E /XD runtime data /IS /IT | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy desktop app failed (exit $LASTEXITCODE)" }
Ok "Mira.exe + resources mirrored (changed files refreshed)"

# ---- 2. python runtime -----------------------------------------------------------
Step "python runtime ($PyVersion embeddable)"
if (-not $skipPython -and -not (Test-Path (Join-Path $PyRuntime "python.exe"))) {
    New-Item -ItemType Directory -Path $PyRuntime -Force | Out-Null
    if (-not (Test-Path $PyZip)) {
        Write-Host "downloading embeddable python..." -ForegroundColor Yellow
        Invoke-WebRequest -UseBasicParsing -Uri $PyUrl -OutFile $PyZip -TimeoutSec 300
    }
    Expand-Archive -Path $PyZip -DestinationPath $PyRuntime -Force

    # Enable `import site` so pip-installed packages are importable, and add the
    # site-packages dir relative to the runtime (keeps it relocatable).
    $pth = Get-ChildItem $PyRuntime -Filter "python3*._pth" | Select-Object -First 1
    $content = Get-Content $pth.FullName
    $content = $content -replace "^import site", "#import site"
    $content = $content -replace "^#\.", "."
    $content = @("# portable site packages", "Lib\site-packages", "import site") + $content
    Set-Content $pth.FullName $content -Encoding ASCII

    # get-pip into the embeddable python.
    if (-not (Test-Path $GetPip)) {
        Invoke-WebRequest -UseBasicParsing -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip -TimeoutSec 120
    }
    & (Join-Path $PyRuntime "python.exe") $GetPip --no-warn-script-location | Out-Host

    # Backend + host dependencies. pip install . resolves pyproject.toml for us.
    # Notes learned the hard way:
    #  * the machine's global pip config may add a broken extra-index (NVIDIA
    #    mirror) — pin pypi.org explicitly;
    #  * the embeddable runtime can't fetch setuptools inside an isolated build
    #    env, so install setuptools/wheel first and skip build isolation.
    $pyExe = Join-Path $PyRuntime "python.exe"
    & $pyExe -m pip install --no-warn-script-location --index-url https://pypi.org/simple setuptools wheel | Out-Host
    & $pyExe -m pip install --no-warn-script-location --index-url https://pypi.org/simple --no-build-isolation "$Backend" | Out-Host
    $hostDeps = Get-Content (Join-Path $Backend "host\requirements.txt") -ErrorAction SilentlyContinue
    if ($hostDeps) {
        & $pyExe -m pip install --no-warn-script-location --index-url https://pypi.org/simple $hostDeps | Out-Host
    }
    Ok "python runtime + deps ready"
} else {
    Ok "using existing runtime\python"
}

# ---- 3. backend source -------------------------------------------------------------
Step "backend source"
if (Test-Path $BackendRuntime) { Remove-Item $BackendRuntime -Recurse -Force }
# Windows reserved device names (NUL, CON, AUX, ...) break Copy-Item — a stray
# `NUL` from a shell redirection was hiding in backend/. Purge any before copying.
Get-ChildItem $Backend -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "^(NUL|CON|PRN|AUX|CLOCK\$|COM[1-9]|LPT[1-9])(\..*)?$" } |
    ForEach-Object { try { [System.IO.File]::Delete("\\?\$($_.FullName)") } catch { } }
# robocopy (not Copy-Item) so /XD reliably excludes .venv, __pycache__, tests, etc.
robocopy $Backend $BackendRuntime /E /XD .venv __pycache__ data tests /XF *.db *.log | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy backend failed (exit $LASTEXITCODE)" }
# The repo .env (token, Gemini key, provider, model names) lives at the repo root,
# not in backend/. The supervisor reads runtime/backend/.env in portable mode, so
# carry it over — without it the bundled app defaults to ollama (not bundled) and
# runs unauthenticated.
if (Test-Path (Join-Path $Root ".env")) {
    Copy-Item (Join-Path $Root ".env") (Join-Path $BackendRuntime ".env") -Force
    Ok "bundled .env (token + provider + keys)"
} else {
    Write-Host "WARNING: repo .env missing - portable app will lack token/provider config" -ForegroundColor Yellow
}
Remove-Item (Join-Path $BackendRuntime "host\.venv") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $BackendRuntime "host\*.log") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $BackendRuntime "host\commands.log") -Force -ErrorAction SilentlyContinue
Ok "backend copied"

# ---- 3b. web app (the UI the desktop window loads) -----------------------------------
Step "web app"
$WebDist = Join-Path $Root "web\dist"
if (-not (Test-Path (Join-Path $WebDist "index.html"))) {
    throw "web app not built - run `npm run build` in web/ first (missing $WebDist\index.html)"
}
# The backend serves the SPA from web/dist next to the runtime (app/main.py
# resolves parents[2]/web/dist = runtime/web/dist in a portable layout). Copy
# it there so the desktop window has a UI to load.
$WebRuntime = Join-Path $Runtime "web\dist"
New-Item -ItemType Directory -Path $WebRuntime -Force | Out-Null
robocopy $WebDist $WebRuntime /E /IS /IT | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy web app failed (exit $LASTEXITCODE)" }
Ok "web app -> runtime\web\dist"

# ---- 4. writable data dir ------------------------------------------------------------
Step "data dir"
New-Item -ItemType Directory -Path (Join-Path $DataDir "models\sherpa") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $DataDir "logs") -Force | Out-Null
Ok "data\models\sherpa, data\logs ready"

# ---- 5. sherpa whisper model (optional) -----------------------------------------------
Step "whisper STT model"
if (-not $skipModels) {
    $whisper = Join-Path $DataDir "models\sherpa\sherpa-onnx-whisper-base.en"
    if (-not (Test-Path (Join-Path $whisper "base.en-encoder.int8.onnx"))) {
        Write-Host "downloading sherpa whisper base.en (~200MB)..." -ForegroundColor Yellow
        $tarball = Join-Path $Temp "sherpa-onnx-whisper-base.en.tar.bz2"
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-base.en.tar.bz2" -OutFile $tarball -TimeoutSec 600
        & (Join-Path $PyRuntime "python.exe") -c "import tarfile; tarfile.open(r'$tarball', 'r:bz2').extractall(r'$DataDir\models\sherpa')"
        Remove-Item $tarball -ErrorAction SilentlyContinue
        Ok "whisper model ready"
    } else { Ok "whisper model already present" }
} else { Ok "skipped (-SkipModels)" }

# ---- 5b. sherpa keyword-spotter model (optional) ---------------------------------------
# The wake-word gate that hears her name before whisper runs. Ships from the repo
# data/models/kws; the resolver looks for the files directly in the model folder.
Step "keyword-spotter model"
if (-not $skipModels) {
    $kwsSrc = Join-Path $Root "data\models\kws\sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
    $kwsDst = Join-Path $DataDir "models\kws\sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
    if (-not (Test-Path (Join-Path $kwsDst "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"))) {
        if (Test-Path $kwsSrc) {
            Copy-Item $kwsSrc $kwsDst -Recurse -Force
            Ok "keyword-spotter model copied"
        } else {
            Write-Host "keyword-spotter model not found in $kwsSrc - wake word gate will be disabled" -ForegroundColor Yellow
        }
    } else { Ok "keyword-spotter model already present" }
} else { Ok "skipped (-SkipModels)" }

# ---- 6. ollama (optional) ----------------------------------------------------------------
Step "ollama"
if ($noOllama) { Ok "skipped (-NoOllama)" }
else {
    $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $ollamaExe) {
        $ollamaDir = Join-Path $Runtime "ollama"
        New-Item -ItemType Directory -Path (Join-Path $ollamaDir "models") -Force | Out-Null
        Copy-Item $ollamaExe (Join-Path $ollamaDir "ollama.exe") -Force
        $modelsHome = Join-Path $env:USERPROFILE ".ollama\models"
        if (Test-Path $modelsHome) {
            Copy-Item "$modelsHome\*" (Join-Path $ollamaDir "models") -Recurse -Force -ErrorAction SilentlyContinue
            Ok "ollama.exe + local models copied"
        } else { Ok "ollama.exe copied (no local models)" }
    } else { Write-Host "ollama not found in $ollamaExe - install Ollama on the build machine to bundle it" -ForegroundColor Yellow }
}

# ---- 7. NSIS installer (optional) -----------------------------------------------
if (-not $skipInstall) {
    Step "installer"
    $nsis = Get-Command makensis -ErrorAction SilentlyContinue
    if (-not $nsis) {
        # winget's NSIS installs here but isn't on PATH
        $candidate = "C:\Program Files (x86)\NSIS\makensis.exe"
        if (Test-Path $candidate) { $nsis = [pscustomobject]@{ Source = $candidate } }
    }
    if ($nsis) {
        $scriptFile = Join-Path $PSScriptRoot "portable_installer.nsi"
        if (Test-Path $scriptFile) {
            & $nsis.Source $scriptFile | Out-Host
            Ok "installer built: dist\Mira Portable Setup.exe"
        } else { Write-Host "portable_installer.nsi not found - skipping installer" -ForegroundColor Yellow }
    } else {
        Write-Host "makensis not found (install NSIS: winget install NSIS.NSIS) - portable folder only" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "portable app ready: $Portable" -ForegroundColor Green
Write-Host "run dist\mira-portable\Mira.exe on any Windows PC - it supervises the whole stack." -ForegroundColor Cyan