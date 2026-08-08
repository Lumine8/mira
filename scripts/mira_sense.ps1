# mira_sense.ps1 — gives Mira eyes on your machine.
#
# Samples a few cheap signals (are you at the machine? what's open?) and pushes
# them as a raw observation to the API's /mira/perceive endpoint, where the mind
# loop lets Mira decide for herself what to make of it.
#
# Run once:
#   powershell -ExecutionPolicy Bypass -File .\scripts\mira_sense.ps1
#
# Run every few minutes (recommended):
#   schtasks /Create /TN "Mira Sense" /TR "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File \"%~dp0..\scripts\mira_sense.ps1\"" /SC MINUTE /MO 5 /F
#
# The URL below assumes the API is published on port 8000 (default). Override
# with -ApiUrl if you changed API_PORT.

param(
    [string]$ApiUrl = "http://localhost:8000"
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class UserActivity {
    [DllImport("user32.dll")]
    public static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
    [StructLayout(LayoutKind.Sequential)]
    public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
}
"@

$lastInput = New-Object UserActivity+LASTINPUTINFO
$lastInput.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($lastInput)
[UserActivity]::GetLastInputInfo([ref]$lastInput) | Out-Null
$idleSeconds = ([Environment]::TickCount - $lastInput.dwTime) / 1000

$idle = if ($idleSeconds -lt 120) {
    "the user is at the machine right now"
} elseif ($idleSeconds -lt 3600) {
    "the machine has been idle for about $([math]::Round($idleSeconds / 60)) minutes"
} else {
    "the machine has been sitting idle for about $([math]::Round($idleSeconds / 3600, 1)) hours"
}

$windows = Get-Process | Where-Object { $_.MainWindowTitle } | Sort-Object CPU -Descending | Select-Object -First 3
$activity = @()
foreach ($p in $windows) {
    $activity += "$($p.ProcessName): $($p.MainWindowTitle)"
}

$content = "$idle."
if ($activity.Count -gt 0) {
    $content += " Open windows: " + ($activity -join " | ")
}

$payload = @{
    source  = "host"
    kind    = "machine"
    content = $content
} | ConvertTo-Json

try {
    Invoke-RestMethod -Method Post -Uri "$ApiUrl/mira/perceive" -ContentType "application/json" -Body $payload | Out-Null
    Write-Output "perceived: $content"
} catch {
    Write-Output "failed to reach Mira at $ApiUrl`: $_"
}
