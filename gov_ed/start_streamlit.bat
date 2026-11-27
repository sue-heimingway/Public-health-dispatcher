@echo off
setlocal
title GovOS Streamlit UI
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
echo   Install from https://www.python.org/downloads/ then double-click again.
echo.
pause
exit /b 1

:havepy
%PY% -c "import streamlit" >nul 2>&1
if not errorlevel 1 goto :run

echo.
echo   First run: installing streamlit, takes 1-2 minutes...
%PY% -m pip install streamlit
echo.

:run
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit" >nul 2>&1
if exist "%USERPROFILE%\.streamlit\credentials.toml" goto :launch
type nul > "%USERPROFILE%\.streamlit\credentials.toml"
echo [general]>> "%USERPROFILE%\.streamlit\credentials.toml"
echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"

:launch
echo   Starting GovOS Streamlit UI ...
echo   Browser will open http://localhost:8501
%PY% -m streamlit run streamlit_app.py
pause