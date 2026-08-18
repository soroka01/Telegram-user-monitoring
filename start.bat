@echo off
setlocal EnableExtensions

chcp 65001 >nul
title TG USERNAME CHECKER - SELL

set "CHECKER_DIR=%~dp0..\telegram_username_checker"
set "CHECKER_START=%CHECKER_DIR%\start.bat"

echo.
echo ========================================================
echo   TG USERNAME CHECKER - STARTING FROM COMPATIBILITY LINK
echo ========================================================
echo Source: %~f0
echo Target: %CHECKER_START%
echo.

if not exist "%CHECKER_START%" (
    echo [ERROR] Username Checker start file was not found:
    echo %CHECKER_START%
    echo.
    pause
    exit /b 1
)

cd /d "%CHECKER_DIR%"
call "%CHECKER_START%"
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%
