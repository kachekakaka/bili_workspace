#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON:-python3}"

"$PYTHON_BIN" tools/verify_source.py
"$PYTHON_BIN" -m compileall -q app tests tools docker
"$PYTHON_BIN" -m ruff check --no-cache app tests tools docker
"$PYTHON_BIN" -m pytest -q -p no:cacheprovider

if command -v node >/dev/null 2>&1; then
  find web -type f -name '*.js' -print0 | xargs -0 -n1 node --check
else
  echo "[跳过] 未安装 Node.js；Python 源码、静态检查和测试已完成。"
fi

echo "[通过] bili_workspace v0.5.4 源码自检完成。"
