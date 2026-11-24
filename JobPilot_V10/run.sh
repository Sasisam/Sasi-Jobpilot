#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PYTHON=""
for candidate in python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: Python 3.10, 3.11, or 3.12 is required."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium || echo "WARNING: Chromium install failed; browser automation may not work."
[ -f .env ] || cp .env.example .env

echo "Starting JobPilot at http://127.0.0.1:8000 (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
