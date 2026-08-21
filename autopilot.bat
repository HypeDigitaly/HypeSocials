@echo off
rem ============================================================================
rem  HypeSocials autopilot (SESSION O / D64)
rem    Starts an unattended Claude Code session that runs the `hypesocials-run`
rem    skill: detached engine run -> wait -> Claude critic panel -> report.
rem    Meant for Windows Task Scheduler (see plans/tools/register_autopilot_task.ps1)
rem    but works by hand too: just double-click or run it from a terminal.
rem    Output: logs\autopilot\<yyyyMMdd_HHmmss>.claude.log ; exit code = claude's.
rem ============================================================================
setlocal EnableExtensions

rem --- UTF-8 first, like run.bat (FR-256) ------------------------------------
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

rem --- always work from the repo root ----------------------------------------
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist "%ROOT%logs\autopilot" mkdir "%ROOT%logs\autopilot"

rem --- timestamp yyyyMMdd_HHmmss (locale independent, via PowerShell) --------
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"`) do set "STAMP=%%T"
set "LOG=%ROOT%logs\autopilot\%STAMP%.claude.log"

rem --- resolve claude: installed shim first, then PATH -----------------------
set "CLAUDE=%USERPROFILE%\.local\bin\claude.exe"
if not exist "%CLAUDE%" (
    for /f "delims=" %%C in ('where claude 2^>nul') do (
        if not defined CLAUDE_FOUND set "CLAUDE=%%C" & set "CLAUDE_FOUND=1"
    )
)
if not exist "%CLAUDE%" (
    echo [%STAMP%] claude not found at %USERPROFILE%\.local\bin\claude.exe nor on PATH >> "%LOG%"
    echo claude not found - see "%LOG%"
    exit /b 9009
)

echo [%STAMP%] autopilot start  claude="%CLAUDE%"  cwd="%ROOT%" >> "%LOG%"

rem --- run the skill headless; stdout+stderr appended to the log -------------
"%CLAUDE%" -p "/hypesocials-run" --dangerously-skip-permissions --output-format text >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

echo [%STAMP%] autopilot end  exit=%RC% >> "%LOG%"
exit /b %RC%
