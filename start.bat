@echo off
setlocal EnableExtensions

cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title User Monitor

echo.
echo User Monitor
echo ============
echo.

set "BOOTSTRAP_PY="
where py >nul 2>&1
if not errorlevel 1 (
    set "BOOTSTRAP_PY=py -3"
) else (
    where python >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PY=python"
)

if not defined BOOTSTRAP_PY (
    echo [ERROR] Python 3 was not found.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Creating local virtual environment...
    %BOOTSTRAP_PY% -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv.
        pause
        exit /b 1
    )
)

set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"

if not exist "config.json" (
    if exist "config.example.json" (
        copy /Y "config.example.json" "config.json" >nul
        echo [OK] Created config.json from config.example.json.
        echo Fill in api_id, api_hash, bot token and monitor.targets before running.
        echo.
        pause
        exit /b 0
    ) else (
        echo [ERROR] config.example.json was not found.
        pause
        exit /b 1
    )
)

echo [SETUP] Installing dependencies into .venv...
set "NO_PROXY=*"
set "no_proxy=*"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
"%PYTHON_CMD%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)
set "NO_PROXY="
set "no_proxy="
set "PIP_DISABLE_PIP_VERSION_CHECK="

echo Starting monitor...
echo.
"%PYTHON_CMD%" "%~dp0main.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo Finished with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
