@echo off
REM ===================================================================
REM  Show the app to a client - one click, no command line.
REM
REM  This starts the console with SAMPLE documents and NO sign-in, so
REM  you can click through the whole workflow immediately.
REM
REM  *** This is for DEMONSTRATION ONLY. ***
REM  *** Never put real client documents into it. ***
REM ===================================================================

title Document Preparation - DEMO

cd /d "%~dp0"

echo ============================================================
echo   DEMONSTRATION MODE
echo ============================================================
echo.
echo   Sample documents only. Do NOT use real client files here.
echo.

set PY=
where py >nul 2>&1 && set PY=py
if "%PY%"=="" (
  where python >nul 2>&1 && set PY=python
)
if "%PY%"=="" (
  echo   Python is not installed. Get it from https://www.python.org/downloads/
  echo   and tick "Add Python to PATH" during installation.
  echo.
  pause
  exit /b 1
)

echo   Checking the program's requirements...
%PY% -m pip install --quiet --disable-pip-version-check pymupdf pillow openpyxl 2>nul

echo   Preparing sample documents and starting up...
echo.

%PY% -u pipeline.py review --demo

echo.
echo   The demo has stopped.
pause
