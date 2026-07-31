#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON:-python3}"

if ! command -v node >/dev/null 2>&1; then
  echo "[阻断] T-PROJECT 完整源码自检要求 Node.js。" >&2
  exit 1
fi

"$PYTHON_BIN" tools/verify_source.py
"$PYTHON_BIN" -m compileall -q app tests tools docker
"$PYTHON_BIN" -m ruff check --no-cache app tests tools docker
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider

find web -type f \( -name '*.js' -o -name '*.mjs' \) -print0 | sort -z | xargs -0 -n1 node --check
node --test tests/frontend/*.test.mjs

echo "[通过] bili_workspace v0.7.0 源码自检完成。"
