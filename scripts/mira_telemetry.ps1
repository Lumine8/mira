# mira_telemetry.ps1 — the machine's live read for Mira's ambient dashboard.
#
# Samples cheap system signals (CPU, memory, battery, top processes, idle time)
# and posts them to the API's /mira/system/report endpoint, where the store
# keeps the latest snapshot plus a rolling history. Runs on the host natively.
#
# Run once:
#   powershell -ExecutionPolicy Bypass -File .\scripts\mira_telemetry.ps1
#
# Run every 30s (recommended — see the schtasks comment in mira_sense.ps1):
#   schtasks /Create /TN "Mira Telemetry" /TR "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%~dp0..\scripts\mira_telemetry.ps1\"" /SC MINUTE /MO 1 /F
#
# Needs the shared token when auth is on: pass -Token or set MIRA_ACCESS_TOKEN.

param(
    [string]$ApiUrl = "http://localhost:8000",
    [string]$Token = $env:MIRA_ACCESS_TOKEN
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class UserActivity2 {
    [DllImport("user32.dll")]
    public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
    [StructLayout(LayoutKind.Sequential)]
    public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
}
"@

$lastInput = New-Object UserActivity2+LASTINPUTINFO
$lastInput.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($lastInput)
[UserActivity2]::GetLastInputInfo([ref]$lastInput) | Out-Null
$idleSeconds = [math]::Max(0, [int](([Environment]::TickCount - $lastInput.dwTime) / 1000))

# CPU total, memory totals/free, battery (desktop machines have none).
try {
    $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop).CounterSamples[0].CookedValue
} catch {
    $cpu = $null
}

$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
$totalMb = $os.TotalVisibleMemorySize / 1024
$freeMb  = $os.FreePhysicalMemory / 1024
$usedMb  = $totalMb - $freeMb

$batt = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
if ($batt) {
    $battPercent = $batt.EstimatedChargeRemaining
    $battCharging = ($batt.BatteryStatus -eq 2)
} else {
    $battPercent = $null
    $battCharging = $null
}

# Top processes by CPU (falling back to working set when CPU is 0 across the board).
$procs = Get-Process | Where-Object { $_.ProcessName } | Sort-Object CPU -Descending | Select-Object -First 5
$top = @()
foreach ($p in $procs) {
    $cpuVal = [math]::Round([double]($p.CPU), 1)
    $top += @{ name = $p.ProcessName; cpu = $cpuVal; mem_mb = [math]::Round($p.WorkingSet64 / 1MB, 1) }
}

$snapshot = @{
    ts                = (Get-Date).ToUniversalTime().ToString("o")
    cpu_percent       = if ($null -ne $cpu) { [math]::Round($cpu, 1) } else { $null }
    memory_percent    = if ($totalMb -gt 0) { [math]::Round(($usedMb / $totalMb) * 100, 1) } else { $null }
    memory_used_mb    = [math]::Round($usedMb, 1)
    memory_total_mb   = [math]::Round($totalMb, 1)
    battery_percent   = $battPercent
    battery_charging  = $battCharging
    idle_seconds      = $idleSeconds
    top_processes     = $top
} | ConvertTo-Json -Depth 4

$headers = @{}
if ($Token) { $headers["X-Mira-Token"] = $Token }

try {
    Invoke-RestMethod -Method Post -Uri "$ApiUrl/mira/system/report" -ContentType "application/json" -Headers $headers -Body $snapshot | Out-Null
    Write-Output "telemetry: cpu=$cpu mem=$([math]::Round($usedMb))/$([math]::Round($totalMb))MB idle=${idleSeconds}s"
} catch {
    Write-Output "failed to reach Mira at $ApiUrl`: $_"
}
