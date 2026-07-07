# Warrior Desk v2 — scheduled-task wrapper (invoked by Windows Task Scheduler).
#   powershell -File warrior_task.ps1 -Mode premarket   # 6:55 AM ET weekdays
#   powershell -File warrior_task.ps1 -Mode session     # 9:23 AM ET weekdays
# Loads keys from secrets.local.ps1 (git-ignored), runs the script, logs to logs\.
#
# NOTE on redirection: python is launched via `cmd /c ... >> log 2>&1` ON PURPOSE.
# Under Windows PowerShell 5.1, piping native stderr (`2>&1 |`) with
# $ErrorActionPreference = "Stop" turns the FIRST stderr line into a fatal
# NativeCommandError — and the startup IEX warning guarantees one, killing the
# task ~1s in. cmd-level redirection also writes python's UTF-8 bytes straight
# to the file (no OEM mojibake of ✓/emoji in the logs).
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
$env:PYTHONUTF8 = "1"
# cmd-level redirection: stderr never touches the PS pipeline (see NOTE above).
cmd /c "python `"$Script`" >> `"$Log`" 2>&1"
$Code = $LASTEXITCODE
Say "$Mode finished with exit code $Code"
exit $Code
