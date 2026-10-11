@echo off
REM ===================================================================
REM  Share with colleagues - double-click this file.
REM
REM  Use this when other people need to open the app from THEIR
REM  computers. It prints the address to give them.
REM
REM  Colleagues in the same building: send them the "Same office"
REM  address it prints.
REM
REM  Colleagues at home: they cannot use that address. You both need
REM  Tailscale installed first - see SETUP.md, "Working from home".
REM
REM  Keep this window open. It IS the server.
REM ===================================================================

title Document Preparation - shared

cd /d "%~dp0"

echo ============================================================
echo   Sharing with colleagues
echo ============================================================
echo.
echo   Colleagues open the address shown below in their browser.
echo   They do not need to install anything.
echo.

set PY=
where py >nul 2>&1 && set PY=py
if "%PY%"=="" (
  where python >nul 2>&1 && set PY=python
)
if "%PY%"=="" (
  echo   Python is not installed on this computer.
  echo   Install it from https://www.python.org/downloads/
  echo   During installation, tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

echo   Checking the program's requirements...
%PY% -m pip install --quiet --disable-pip-version-check pymupdf pillow openpyxl 2>nul

echo.
echo   If Windows asks whether to allow Python, choose ALLOW.
echo   Without it, nobody else can connect.
echo.

%PY% -u pipeline.py share

echo.
echo   Sharing has stopped. Colleagues can no longer connect.
pause
