#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Web Novel Scraper"

cd "$(dirname "$0")"

if ! python -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller is not installed for this Python environment."
  echo "Install it with:"
  echo "  python -m pip install pyinstaller"
  exit 1
fi

python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --add-data "readnovelfull.py:." \
  --add-data "webnoveltranslations.py:." \
  --add-data "novelbin.py:." \
  main.py

echo
echo "Built app:"
echo "  dist/$APP_NAME.app"
