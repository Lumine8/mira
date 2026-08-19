# fix_cloudflared_service.ps1 -- make Mira's permanent tunnel a real service.
#
# The cloudflared Windows service runs as LocalSystem, so it reads its config
# from the SYSTEM profile (C:\Windows\System32\config\systemprofile\.cloudflared)
# -- not the human user's ~/.cloudflared. If that directory is empty the service
# dies at boot with exit code 1067, which is why the tunnel has historically
# been babysat in an elevated shell instead of just working.
#
# This script fixes that permanently:
#   1. Copies config.yml, cert.pem, and the tunnel credentials into the SYSTEM
#      profile location (where the service actually looks).
#   2. Rewrites the credentials-file path in the copied config so LocalSystem
#      reads its own copy, not the user's.
#   3. Starts the service (Automatic, on boot).
#
# Run once, elevated (it re-launches itself with UAC if needed):
#   powershell -ExecutionPolicy Bypass -File .\scripts\fix_cloudflared_service.ps1

param(
    [string]$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    [switch]$SkipElevate
)

$ErrorActionPreference = "Stop"

# ---- self-elevate ------------------------------------------------------------

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin -and -not $SkipElevate) {
    Write-Host "requesting administrator rights to write to the SYSTEM profile..."
    $script = "& { $($MyInvocation.MyCommand.Path) -SkipElevate }"
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $script
    exit 0
}
if (-not $isAdmin) {
    Write-Host "not elevated; cannot write to the SYSTEM profile. aborting."
    exit 1
}

# ---- locate the pieces --------------------------------------------------------

$userCloudflared = "$env:USERPROFILE\.cloudflared"
if (-not (Test-Path -LiteralPath $userCloudflared)) {
    Write-Host "no ~/.cloudflared found at $userCloudflared -- nothing to provision."
    exit 1
}

$configSrc = Join-Path $userCloudflared "config.yml"
if (-not (Test-Path -LiteralPath $configSrc)) {
    Write-Host "no config.yml in $userCloudflared -- nothing to provision."
    exit 1
}

# Tunnel id + credentials file come from the existing config.
$tunnelId = $null
$credSrc = $null
foreach ($line in Get-Content -LiteralPath $configSrc) {
    if ($line -match "^\s*tunnel:\s*(\S+)\s*$") { $tunnelId = $Matches[1] }
    if ($line -match "^\s*credentials-file:\s*(.+?)\s*$") { $credSrc = $Matches[1].Trim('"') }
}
if (-not $tunnelId) { Write-Host "could not read tunnel id from config.yml."; exit 1 }
if (-not $credSrc -or -not (Test-Path -LiteralPath $credSrc)) {
    # Fall back to the conventional name next to the config.
    $candidate = Join-Path $userCloudflared "$tunnelId.json"
    if (Test-Path -LiteralPath $candidate) { $credSrc = $candidate }
}
if (-not $credSrc -or -not (Test-Path -LiteralPath $credSrc)) {
    Write-Host "could not find the tunnel credentials file for tunnel $tunnelId."
    exit 1
}

$certSrc = Join-Path $userCloudflared "cert.pem"

# ---- provision the SYSTEM profile copy -----------------------------------------

$sysCloudflared = "C:\Windows\System32\config\systemprofile\.cloudflared"
New-Item -ItemType Directory -Force -Path $sysCloudflared | Out-Null

$credDest = Join-Path $sysCloudflared "$tunnelId.json"
Copy-Item -LiteralPath $credSrc -Destination $credDest -Force
Write-Host "credentials -> $credDest"

if (Test-Path -LiteralPath $certSrc) {
    Copy-Item -LiteralPath $certSrc -Destination (Join-Path $sysCloudflared "cert.pem") -Force
    Write-Host "cert.pem -> SYSTEM profile"
}

# Rewrite the config for the SYSTEM context: credentials-file must point at the
# copy we just made, and the ingress stays localhost:8080.
$configDest = Join-Path $sysCloudflared "config.yml"
$rewritten = @()
foreach ($line in Get-Content -LiteralPath $configSrc) {
    if ($line -match "^\s*credentials-file:") {
        $rewritten += "credentials-file: $credDest"
    } else {
        $rewritten += $line
    }
}
Set-Content -LiteralPath $configDest -Value $rewritten -Encoding UTF8
Write-Host "config -> $configDest (credentials-file pointed at the SYSTEM copy)"

# ---- align the service and start it --------------------------------------------

$service = Get-Service -Name cloudflared -ErrorAction SilentlyContinue
if ($service) {
    $bin = "`"$Cloudflared`" --no-autoupdate tunnel --config `"$configDest`" run mira"
    sc.exe config cloudflared binPath= $bin | Out-Null
    if ($?) { Write-Host "service binary path aligned to the SYSTEM config" }
    Start-Service -Name cloudflared
    Start-Sleep -Seconds 6
    $svc = Get-Service -Name cloudflared
    Write-Host "cloudflared service: $($svc.Status)"
    if ($svc.Status -eq "Running") {
        Write-Host "Mira's tunnel is up at https://mira.mousebase.dev"
    } else {
        Write-Host "service did not reach Running. check: Get-WinEvent -LogName System | Where-Object { `$_.ProviderName -eq 'Service Control Manager' }"
        exit 1
    }
} else {
    Write-Host "no cloudflared service installed -- installing one..."
    & $Cloudflared service install | Out-Null
    Start-Service -Name cloudflared
    Write-Host "cloudflared service installed and started."
}