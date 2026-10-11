@echo off
REM ===================================================================
REM  Start the document preparation console - one click, no command line.
REM
REM  Double-click this file.
REM
REM  - The first time, it sets up sample documents so you have something
REM    to look at.
REM  - Your browser opens automatically.
REM  - Close this black window (or press Ctrl+C) to stop the app.
REM ===================================================================

title Document Preparation - running

cd /d "%~dp0"

echo ============================================================
echo   Starting the document preparation console
echo ============================================================
echo.

REM Find Python.
set PY=
where py >nul 2>&1 && set PY=py
if "%PY%"=="" (
  where python >nul 2>&1 && set PY=python
)
if "%PY%"=="" (
  echo   Python is not installed on this computer.
  echo.
  echo   Install it from https://www.python.org/downloads/
  echo   During installation, tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

REM Install what the app needs, quietly. Safe to repeat.
echo   Checking the program's requirements...
%PY% -m pip install --quiet --disable-pip-version-check pymupdf pillow openpyxl 2>nul

echo   Starting up. Your browser will open in a moment.
echo.
echo   Leave this window open while you work.
echo   Press Ctrl+C or close this window when you are finished.
echo.

%PY% pipeline.py review --users

echo.
echo   The console has stopped.
pause
