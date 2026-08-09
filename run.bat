@echo off
rem ============================================================================
rem  HypeSocials — single entry point (30-configuration-and-run.md §3)
rem    FR-53  bootstrap .venv on first run, reuse it afterwards
rem    FR-54  forward every argument to the engine unmodified
rem    FR-55  pause on interactive exits only; with --yes exit immediately
rem    FR-256 UTF-8 console + PYTHONIOENCODING before anything launches
rem    FR-113 pre-install the PINNED Notion MCP server; never resolve at run time
rem    FR-138 refuse to start on an interpreter below the required version
rem ============================================================================
setlocal EnableExtensions EnableDelayedExpansion

rem --- FR-256: UTF-8 first, before any output or any child process ------------
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "ROOT=%~dp0"
set "ROOT_NOSLASH=%ROOT:~0,-1%"
set "VENV=%ROOT%.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"
set "MIN_PY=3.12"
rem FR-113: the one authoritative pin for the Notion MCP server package.
set "NOTION_MCP_PIN=2.5.1"

rem --- FR-55: unattended runs (--yes) must never pause -------------------------
set "INTERACTIVE=1"
for %%A in (%*) do if /I "%%~A"=="--yes" set "INTERACTIVE=0"

if not exist "%VENV_PY%" call :create_venv || goto :bootstrap_failed
call :check_python || goto :bootstrap_failed
call :sync_deps || goto :bootstrap_failed
call :bootstrap_notion_mcp

rem --- FR-54: arguments pass through untouched --------------------------------
"%VENV_PY%" -m hypesocials %*
set "CODE=%ERRORLEVEL%"
if "%INTERACTIVE%"=="1" pause
exit /b %CODE%

rem ---------------------------------------------------------------------------
:bootstrap_failed
echo.
echo [run.bat] Bootstrap failed - the run did not start, nothing was spent.
if "%INTERACTIVE%"=="1" pause
exit /b 1

rem --- FR-53 / FR-138: create the venv with a new-enough interpreter ----------
:create_venv
echo [run.bat] First run: creating the virtual environment in .venv ...
set "BOOT_PY="
for %%C in ("py -3.13" "py -3.12" "py -3" "python") do (
    if not defined BOOT_PY (
        %%~C -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
        if !ERRORLEVEL! EQU 0 set "BOOT_PY=%%~C"
    )
)
if not defined BOOT_PY (
    echo [run.bat] ERROR: no Python %MIN_PY%+ interpreter was found on PATH.
    echo           Install Python 3.13 from python.org, tick "Add python.exe to PATH", then re-run this file.
    exit /b 1
)
%BOOT_PY% -m venv "%VENV%"
if errorlevel 1 (
    echo [run.bat] ERROR: could not create the virtual environment at "%VENV%".
    exit /b 1
)
exit /b 0

rem --- FR-138: an existing venv must still meet the minimum version -----------
:check_python
if not exist "%VENV_PY%" (
    echo [run.bat] ERROR: "%VENV_PY%" is missing. Delete the .venv folder and re-run to rebuild it.
    exit /b 1
)
"%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [run.bat] ERROR: the .venv interpreter is older than Python %MIN_PY%.
    echo           Delete the .venv folder and re-run this file to rebuild it on a newer Python.
    exit /b 1
)
exit /b 0

rem --- FR-53: idempotent dependency sync; reinstall only when pins moved ------
:sync_deps
set "STAMP=%VENV%\.deps-stamp"
set "PJ_TS="
for %%F in ("%ROOT%pyproject.toml") do set "PJ_TS=%%~tF"
if exist "%STAMP%" (
    set "OLD_TS="
    set /p OLD_TS=<"%STAMP%"
    if "!OLD_TS!"=="%PJ_TS%" exit /b 0
)
echo [run.bat] Installing Python dependencies (this only happens when pins change) ...
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet --upgrade pip
if errorlevel 1 (
    echo [run.bat] ERROR: could not upgrade pip inside the virtual environment.
    exit /b 1
)
"%VENV_PY%" -m pip install --disable-pip-version-check --quiet --editable "%ROOT_NOSLASH%"
if errorlevel 1 (
    echo [run.bat] ERROR: dependency installation failed. Check the network connection and pyproject.toml pins.
    exit /b 1
)
> "%STAMP%" echo %PJ_TS%
exit /b 0

rem --- FR-113: pinned, pre-installed Notion MCP server; Node is optional ------
:bootstrap_notion_mcp
set "NOTION_STAMP=%ROOT%node_modules\.notion-mcp-%NOTION_MCP_PIN%.ok"
if exist "%NOTION_STAMP%" exit /b 0
where npm >nul 2>&1
if errorlevel 1 (
    echo [run.bat] WARNING: Node/npm not found - skipping the pinned Notion MCP server install.
    echo           Notion brand context is optional; leave notion_influence at "off", or install Node.js and re-run.
    exit /b 0
)
echo [run.bat] Installing pinned Notion MCP server @notionhq/notion-mcp-server@%NOTION_MCP_PIN% ...
call npm install --prefix "%ROOT_NOSLASH%" --no-audit --no-fund --silent "@notionhq/notion-mcp-server@%NOTION_MCP_PIN%"
if errorlevel 1 (
    echo [run.bat] WARNING: the Notion MCP server install failed - continuing without it; Notion is optional.
    exit /b 0
)
> "%NOTION_STAMP%" echo ok
exit /b 0
