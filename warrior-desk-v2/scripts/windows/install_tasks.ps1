# Warrior Desk v2 — install the daily Windows scheduled tasks (run ONCE).
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install_tasks.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install_tasks.ps1 -Uninstall
#
# Creates two weekday tasks (times are your LOCAL clock — you are in ET, which
# is what the market windows expect):
#   WarriorDesk Premarket  6:55 AM  -> gapper scan, freezes the watchlist at 9:15
#   WarriorDesk Session    9:23 AM  -> trades paper hands-off until the close
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"

$TaskNames = @("WarriorDesk Premarket", "WarriorDesk Session")
if ($Uninstall) {
    foreach ($n in $TaskNames) {
        Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Host "Removed Warrior Desk scheduled tasks."
    exit 0
}

$Wrapper = Join-Path (Split-Path $PSCommandPath -Parent) "warrior_task.ps1"
if (-not (Test-Path $Wrapper)) { throw "warrior_task.ps1 not found next to this script" }

$Days = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
$Settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 9) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)

$Jobs = @(
    @{ Name = "WarriorDesk Premarket"; Mode = "premarket"; At = "6:55AM" },
    @{ Name = "WarriorDesk Session";   Mode = "session";   At = "9:23AM" }
)
foreach ($j in $Jobs) {
    $Action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"{0}`" -Mode {1}" -f $Wrapper, $j.Mode)
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $j.At
    Register-ScheduledTask -TaskName $j.Name -Action $Action -Trigger $Trigger `
        -Settings $Settings -Description "Warrior Desk v2 paper-trading agent (educational; paper only)" `
        -Force | Out-Null
    Write-Host ("Installed: {0}  (weekdays {1})" -f $j.Name, $j.At)
}
Write-Host ""
Write-Host "Done. Logs land in warrior-desk-v2\logs\ ; reports in warrior-desk-v2\reports\ ."
Write-Host "Reminders:"
Write-Host " - PC on or asleep with wake timers allowed (Power Options > Sleep > Allow wake timers)."
Write-Host " - Stay LOGGED IN (locked screen is fine): these tasks run in your interactive session."
Write-Host " - Sync the clock tonight:  w32tm /resync   (the agent aborts on >5s skew)."
