<#
.SYNOPSIS
    Registers (or re-registers) the Windows Task Scheduler task "HypeSocials Autopilot".

.DESCRIPTION
    The task runs autopilot.bat from the repo root once a day (default 07:00 local),
    as the current user, -RunLevel Limited, ONLY when the user is logged on
    (interactive token). That last part matters: the Codex OAuth login and the
    Claude Code login both live in the user profile and are not reachable from a
    "run whether user is logged on or not" (S4U / stored-password) token.

    Idempotent: an existing task with the same name is unregistered first.

    Windows PowerShell 5.1 compatible (no &&, no ternary).

.PARAMETER At
    Daily start time, "HH:mm" 24-hour local. Default "07:00".

.PARAMETER TaskName
    Default "HypeSocials Autopilot".

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File plans\tools\register_autopilot_task.ps1
    powershell -ExecutionPolicy Bypass -File plans\tools\register_autopilot_task.ps1 -At 06:30
#>
[CmdletBinding()]
param(
    [string]$At = "07:00",
    [string]$TaskName = "HypeSocials Autopilot"
)

$ErrorActionPreference = "Stop"

# --- locate the repo root from this file (plans\tools\ -> repo) --------------
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Bat = Join-Path $RepoRoot "autopilot.bat"
if (-not (Test-Path $Bat)) {
    throw "autopilot.bat not found at $Bat"
}

# --- validate the time ------------------------------------------------------
$parsed = $null
if (-not [DateTime]::TryParseExact($At, "HH:mm", $null, [System.Globalization.DateTimeStyles]::None, [ref]$parsed)) {
    throw "-At must be HH:mm (24h), got '$At'"
}

# --- idempotent: drop the old one -------------------------------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    Write-Host "Task '$TaskName' exists - replacing it."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# --- build the task ---------------------------------------------------------
# cmd /c so the .bat's exit code and its own redirections behave exactly as by hand.
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument ('/c ""' + $Bat + '""') `
    -WorkingDirectory $RepoRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At $At

# Interactive token = only when the user is logged on; Limited = no elevation.
$UserId = "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

# A run is 40-60 min plus the review; give it 3 h, never run two at once,
# start late if the machine was asleep, stay alive on battery.
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "HypeSocials autopilot: unattended Claude Code session runs the engine, reviews every deck, writes output/<run>/CLAUDE_REVIEW.md and logs/autopilot/AUTOPILOT_LOG.md." | Out-Null

Write-Host ""
Write-Host "Registered '$TaskName'"
Write-Host "  runs     : daily at $At (local), only while $UserId is logged on"
Write-Host "  command  : cmd /c ""$Bat"""
Write-Host "  cwd      : $RepoRoot"
Write-Host "  logs     : $RepoRoot\logs\autopilot\"
Write-Host ""
Write-Host "Change the time : powershell -ExecutionPolicy Bypass -File ""$PSCommandPath"" -At 06:30"
Write-Host "Run it now      : Start-ScheduledTask -TaskName ""$TaskName"""
Write-Host "Disable         : Disable-ScheduledTask -TaskName ""$TaskName"""
Write-Host "Enable again    : Enable-ScheduledTask -TaskName ""$TaskName"""
Write-Host "Remove          : Unregister-ScheduledTask -TaskName ""$TaskName"" -Confirm:`$false"
Write-Host "Last result     : (Get-ScheduledTaskInfo -TaskName ""$TaskName"").LastTaskResult"
