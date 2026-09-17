#!/usr/bin/env bash
# Phase 06 development bootstrap script.
# Sets up a fresh clone of NETSCOPE-X end-to-end: Python venv + backend deps,
# frontend npm deps. Run from the repository root:
#   bash scripts/setup.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Backend: creating .venv and installing pinned dependencies =="
python -m venv .venv
if [ -f .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe   # Windows venv layout
else
  PY=.venv/bin/python           # POSIX venv layout
fi
"$PY" -m pip install --disable-pip-version-check --upgrade pip
"$PY" -m pip install --disable-pip-version-check -r requirements-dev.txt

echo "== Backend: running data-contract validation and smoke tests =="
"$PY" -m scripts.validate_data_contracts
"$PY" -m pytest backend/tests -q

echo "== Frontend: installing npm dependencies =="
(cd frontend && npm install)

echo "== Setup complete =="
