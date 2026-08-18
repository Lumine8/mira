$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$senseScript = Join-Path $root "scripts\mira_sense.ps1"
if (-not (Test-Path -LiteralPath $senseScript)) {
    $root = (Resolve-Path (Join-Path $root "..")).Path
    $senseScript = Join-Path $root "scripts\mira_sense.ps1"
}
# Run once now, then every 5 minutes, forever. The script itself is a one-shot
# sampler; this loop is what makes Mira's eyes continuous without needing
# admin rights for schtasks.
while ($true) {
    if (Test-Path -LiteralPath $senseScript) {
        & powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File $senseScript
    }
    Start-Sleep -Seconds 300
}