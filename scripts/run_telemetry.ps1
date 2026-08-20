# Mira Telemetry scheduled-task wrapper: injects the access token and runs the
# telemetry sampler. Location-independent — resolves its own directory, reads the
# token from the sibling .env (installed bundle) or repo root, and calls the
# sampler in the same folder. This is what both the repo and the installer's
# scheduled task invoke, so the task path never goes stale.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$sampler = Join-Path $here "mira_telemetry.ps1"

# Token: explicit env wins; then the installed bundle's runtime/backend/.env;
# then the repo-root .env (which the portable build also carries into the bundle).
if (-not $env:MIRA_ACCESS_TOKEN) {
    foreach ($candidate in @(
            (Join-Path $here "..\runtime\backend\.env"),
            (Join-Path $here "..\.env")
        )) {
        if (Test-Path $candidate) {
            $line = Select-String -Path $candidate -Pattern '^MIRA_ACCESS_TOKEN=' | Select-Object -First 1
            if ($line) {
                $env:MIRA_ACCESS_TOKEN = $line.Line.Split('=', 2)[1].Trim()
                break
            }
        }
    }
}

& $sampler