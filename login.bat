@echo off
setlocal EnableExtensions

cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title User Monitor Login

echo.
echo User Monitor Login
echo ==================
echo.

set "BOOTSTRAP_PY="
where py >nul 2>&1
if not errorlevel 1 (
    set "BOOTSTRAP_PY=py -3.14"
) else (
    where python >nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PY=python"
)

if not defined BOOTSTRAP_PY (
    echo [ERROR] Python 3.14 or newer was not found.
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

"%PYTHON_CMD%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .venv uses Python older than 3.14.
    echo [ACTION] Recreate .venv with Python 3.14 or newer.
    pause
    exit /b 1
)

if not exist "config.json" (
    if exist "config.example.json" copy /Y "config.example.json" "config.json" >nul
    echo Fill config.json first, then run login.bat again.
    pause
    exit /b 1
)

echo [SETUP] Installing dependencies into .venv...
set "NO_PROXY=*"
set "no_proxy=*"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
"%PYTHON_CMD%" -m pip install --quiet --upgrade "pip==26.1.2" "setuptools==84.0.0" "wheel==0.48.0"
if errorlevel 1 (
    echo [ERROR] Could not update Python tools in .venv.
    pause
    exit /b 1
)
"%PYTHON_CMD%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)
set "NO_PROXY="
set "no_proxy="
set "PIP_DISABLE_PIP_VERSION_CHECK="

"%PYTHON_CMD%" "%~dp0login.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
pause
exit /b %EXIT_CODE%
