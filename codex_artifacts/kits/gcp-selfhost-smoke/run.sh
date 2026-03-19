#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SMOKE_DIR="$ROOT_DIR/codex_artifacts/kits/gcp-selfhost-smoke"
VENV_DIR="$SMOKE_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -r "$SMOKE_DIR/requirements.txt" >/dev/null
"$VENV_DIR/bin/python" "$SMOKE_DIR/run_smoke.py"
