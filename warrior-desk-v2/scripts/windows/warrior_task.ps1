# Warrior Desk v2 — scheduled-task wrapper (invoked by Windows Task Scheduler).
#   powershell -File warrior_task.ps1 -Mode premarket   # 6:55 AM ET weekdays
#   powershell -File warrior_task.ps1 -Mode session     # 9:23 AM ET weekdays
# Loads keys from secrets.local.ps1 (git-ignored), runs the script, logs to logs\.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("premarket", "session")]
    [string]$Mode
)
$ErrorActionPreference = "Stop"

# repo root = ...\warrior-desk-v2 (this file lives in scripts\windows\)
$Repo = Split-Path (Split-Path (Split-Path $PSCommandPath -Parent) -Parent) -Parent
Set-Location $Repo
New-Item -ItemType Directory -Force -Path (Join-Path $Repo "logs") | Out-Null
$Log = Join-Path $Repo ("logs\task_{0}_{1}.log" -f $Mode, (Get-Date -Format "yyyy-MM-dd"))

function Say([string]$msg) {
    "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg |
        Out-File -FilePath $Log -Append -Encoding utf8
}

# Double weekday guard (the trigger is weekday-only; this covers manual runs).
if ((Get-Date).DayOfWeek -in @("Saturday", "Sunday")) {
    Say "weekend - nothing to do"
    exit 0
}

$Secrets = Join-Path $Repo "secrets.local.ps1"
if (-not (Test-Path $Secrets)) {
    Say "ERROR: secrets.local.ps1 not found - copy secrets.local.ps1.example and fill in your PAPER keys"
    exit 2
}
. $Secrets

$Script = if ($Mode -eq "premarket") { "scripts\run_premarket.py" } else { "scripts\run_session.py" }
Say "starting $Mode ($Script)"
# UTF-8 everywhere: the reports/journal contain unicode and Windows defaults to cp1252.
$env:PYTHONUTF8 = "1"
& python $Script 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
$Code = $LASTEXITCODE
Say "$Mode finished with exit code $Code"
exit $Code
