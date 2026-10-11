#!/usr/bin/env bash
# ===================================================================
#  Start the document preparation console - macOS and Linux.
#
#  Double-click (macOS) or run:  ./start-mac-linux.command
#
#  The first time, you will create your account in the browser.
#  Press Ctrl+C in this window to stop the app.
# ===================================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "  Starting the document preparation console"
echo "============================================================"
echo

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "  Python is not installed."
  echo "  macOS:  brew install python"
  echo "  Ubuntu: sudo apt install python3 python3-pip"
  echo
  read -r -p "Press Enter to close..." _
  exit 1
fi

echo "  Checking the program's requirements..."
"$PY" -m pip install --quiet --disable-pip-version-check pymupdf pillow openpyxl 2>/dev/null || true

echo "  Starting up. Your browser will open in a moment."
echo "  Leave this window open while you work."
echo

"$PY" pipeline.py review --users

echo
read -r -p "The console has stopped. Press Enter to close..." _
