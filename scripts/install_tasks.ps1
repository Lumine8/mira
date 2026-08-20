# install_tasks.ps1 — registers (or removes) Mira's host scheduled tasks.
#
# Called by the NSIS installer at the end of install so a fresh install has the
# HUD metrics (Mira Telemetry, every 1 min) and the mind-loop observations
# (Mira Sense, every 5 min) without any manual step. Safe to re-run: -Force
# overwrites the tasks with paths relative to this script's own directory, so a
# reinstall at a new $INSTDIR just re-points them.
#
# Usage:
#   powershell -File install_tasks.ps1            (register both tasks)
#   powershell -File install_tasks.ps1 -Uninstall (remove both tasks)
#
# No admin needed: these run in the installing user's session.

param(
    [switch]$Uninstall
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function New-WrapperTask {
    param(
        [string]$Name,
        [string]$Wrapper,
        [int]$Minutes
    )
    $wrapperPath = Join-Path $here $Wrapper
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapperPath`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Minutes)
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force
    Write-Output "registered scheduled task: $Name -> $wrapperPath (every $Minutes min)"
}

if ($Uninstall) {
    foreach ($name in @("Mira Telemetry", "Mira Sense")) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Output "removed scheduled task: $name"
        }
    }
    exit 0
}

New-WrapperTask -Name "Mira Telemetry" -Wrapper "run_telemetry.ps1" -Minutes 1
New-WrapperTask -Name "Mira Sense" -Wrapper "run_sense.ps1" -Minutes 5