#!/usr/bin/env bash
# Epsilon dev environment setup — used by the Claude Code SessionStart hook
# and by contributors. Idempotent.
set -e
cd "$(dirname "$0")/.."
python3 -m pip install -q -e ".[server,dev]" 2>/dev/null || \
  python3 -m pip install -q pytest fastapi uvicorn httpx 2>/dev/null || true
echo "Epsilon environment ready. Run: python3 -m pytest -q"
