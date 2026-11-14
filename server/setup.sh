#!/bin/sh
# One-time setup: Vexo kit + Python environment. Run from the server/ folder.
set -e
cd "$(dirname "$0")"
[ -d vexo-open-kit ] || git clone --depth 1 https://github.com/VexoAI-Org/vexo-open-kit
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Ready. Edit server/.env, then: .venv/bin/python -m tools.tap_probe --sim"
