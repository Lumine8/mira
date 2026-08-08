$ErrorActionPreference = "Continue"
$hostDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $hostDir
$py = Join-Path $hostDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    Start-Transcript -LiteralPath (Join-Path $hostDir "start_agent_err.log") -Append
    Write-Output "[$(Get-Date)] venv python missing at $py"
    Stop-Transcript
    exit 1
}
# Only start one instance.
$existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*agent.py*" }
if ($existing) {
    exit 0
}
Start-Process -FilePath $py -ArgumentList 'agent.py' -WorkingDirectory $hostDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $hostDir "agent_run_stdout.log") `
    -RedirectStandardError  (Join-Path $hostDir "agent_run_stderr.log")