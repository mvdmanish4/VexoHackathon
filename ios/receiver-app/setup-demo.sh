#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null; then
    echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

if [[ ! -d vexo-open-kit/.git ]]; then
    git clone https://github.com/VexoAI-Org/vexo-open-kit.git
    git -C vexo-open-kit checkout --detach 1e4291e2fa4896b1f603d3d4f0b009c483425da0
fi

uv sync --locked --extra band
if [[ ! -e .env ]]; then
    (umask 077; cp .env.example .env)
fi
uv run --locked --no-sync python - <<'PY'
from secrets import token_urlsafe
from dotenv import dotenv_values, set_key

code = (dotenv_values(".env").get("VEXO_RECEIVER_CODE") or "").strip()
if not code:
    code = token_urlsafe(18)
    set_key(".env", "VEXO_RECEIVER_CODE", code)
print(f"iPhone receiver code: {code}")
PY
local_name="$(scutil --get LocalHostName 2>/dev/null || true)"
if [[ -n "$local_name" ]]; then
    echo "iPhone receiver address: http://${local_name}.local:8765"
fi
echo "Open http://localhost:8765 and click Send simulated turn to try the demo."
exec uv run --locked --no-sync uvicorn server:app --host 0.0.0.0 --port 8765
