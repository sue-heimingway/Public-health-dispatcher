@echo off
setlocal
title GovOS
cd /d "%~dp0"

set "PY="
py -3 -V >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto :havepy
)
python -V >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto :havepy
)
python3 -V >nul 2>&1
if not errorlevel 1 (
    set "PY=python3"
    goto :havepy
)
echo.
echo   [ERROR] Python 3.10+ not found.
echo   Install from https://www.python.org/downloads/
echo   Tick "Add Python to PATH" during setup, then double-click this file again.
echo.
pause
exit /b 1

:havepy
%PY% run.py %*
if errorlevel 1 (
    echo.
    echo   Startup failed. Please send the message above to me.
    pause
)