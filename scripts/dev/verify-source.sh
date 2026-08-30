#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[阻断] T-PROJECT 完整源码自检要求 Python。" >&2
  exit 1
fi

if ! RUN_ROOT=$("$PYTHON_BIN" -B -X utf8 tools/t_project_isolation.py create --workspace-root "$ROOT"); then
  echo "[阻断] 无法创建 T-PROJECT 仓库外隔离运行目录。" >&2
  exit 1
fi
RESULTS_DIR="$RUN_ROOT/results"

finish() {
  code=$?
  trap - EXIT HUP INT TERM
  if "$PYTHON_BIN" -B -X utf8 tools/t_project_isolation.py cleanup \
    --workspace-root "$ROOT" \
    --run-root "$RUN_ROOT" >/dev/null; then
    echo "隔离运行目录已清理：$RUN_ROOT"
  else
    echo "[失败] 无法精确清理隔离运行目录：$RUN_ROOT" >&2
    if [ "$code" -eq 0 ]; then
      code=1
    fi
  fi
  exit "$code"
}

trap finish EXIT
trap 'exit 130' HUP INT TERM

export BILI_VERIFY_RUN_ROOT="$RUN_ROOT"
export BILI_APP_MODE=local
export BILI_CONFIG_DIR="$RUN_ROOT/config"
export BILI_USERDATA_DIR="$RUN_ROOT/userdata"
export BILI_MEDIA_DIR="$RUN_ROOT/downloads"
export BILI_CACHE_DIR="$RUN_ROOT/userdata/cache"
export BILI_TEMP_DIR="$RUN_ROOT/tmp"
export BILI_BBDOWN_DIR="$RUN_ROOT/config/bbdown"
export HOME="$RUN_ROOT/home"
export XDG_CACHE_HOME="$RUN_ROOT/userdata/cache"
export PYTHONPYCACHEPREFIX="$RUN_ROOT/pycache"
export TMPDIR="$RUN_ROOT/tmp"
export TEMP="$RUN_ROOT/tmp"
export TMP="$RUN_ROOT/tmp"
mkdir -p "$BILI_CACHE_DIR"

if ! command -v node >/dev/null 2>&1; then
  echo "[阻断] T-PROJECT 完整源码自检要求 Node.js。" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -B -X utf8 -c 'import fastapi,httpx,pydantic,playwright,pytest,ruff,starlette,uvicorn' >"$RESULTS_DIR/python-dependencies.log" 2>&1; then
  cat "$RESULTS_DIR/python-dependencies.log" >&2
  echo "[阻断] T-PROJECT 完整源码自检缺少项目锁定的 Python 开发依赖。" >&2
  exit 1
fi

if "$PYTHON_BIN" -B -X utf8 tools/playwright_runtime.py \
  --workspace-root "$ROOT" \
  --run-root "$RUN_ROOT" \
  --probe >"$RESULTS_DIR/playwright-browser.path" 2>"$RESULTS_DIR/playwright-runtime.log"; then
  BILI_PLAYWRIGHT_CHROMIUM=$(tr -d '\r' <"$RESULTS_DIR/playwright-browser.path")
  if [ -z "$BILI_PLAYWRIGHT_CHROMIUM" ]; then
    echo "[不确定] 浏览器运行器未返回可用路径。" >&2
    exit 1
  fi
  export BILI_PLAYWRIGHT_CHROMIUM
  export BILI_RUN_PLAYWRIGHT=1
else
  playwright_exit=$?
  cat "$RESULTS_DIR/playwright-runtime.log" >&2
  if [ "$playwright_exit" -eq 3 ]; then
    echo "[阻断] T-PROJECT full 要求可用的既有 Playwright 浏览器。" >&2
  else
    echo "[不确定] Playwright 浏览器运行器异常。" >&2
  fi
  exit 1
fi

if ! "$PYTHON_BIN" -B -X utf8 -m tools.config_sync >"$RESULTS_DIR/config-sync.log" 2>&1; then
  cat "$RESULTS_DIR/config-sync.log" >&2
  echo "[失败] 隔离配置同步失败。" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -B -X utf8 tools/verify_source.py >"$RESULTS_DIR/verify-source.log" 2>&1; then
  cat "$RESULTS_DIR/verify-source.log" >&2
  echo "[失败] 源码安全边界检查失败。" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -B -X utf8 -m compileall -q app tests tools docker >"$RESULTS_DIR/compileall.log" 2>&1; then
  cat "$RESULTS_DIR/compileall.log" >&2
  echo "[失败] Python 编译检查失败。" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -B -X utf8 -m ruff check --no-cache app tests tools docker >"$RESULTS_DIR/ruff.log" 2>&1; then
  cat "$RESULTS_DIR/ruff.log" >&2
  echo "[失败] Ruff 检查失败。" >&2
  exit 1
fi
if ! (
  unset BILI_VERIFY_RUN_ROOT BILI_APP_MODE
  unset BILI_DATABASE_PATH
  "$PYTHON_BIN" -B -X utf8 -m pytest -q -p no:cacheprovider --basetemp "$RUN_ROOT/pytest"
) >"$RESULTS_DIR/pytest.log" 2>&1; then
  cat "$RESULTS_DIR/pytest.log" >&2
  echo "[失败] Pytest 检查失败。" >&2
  exit 1
fi

if ! find web -type f \( -name '*.js' -o -name '*.mjs' \) -print0 | sort -z | xargs -0 -n1 node --check >"$RESULTS_DIR/node-syntax.log" 2>&1; then
  cat "$RESULTS_DIR/node-syntax.log" >&2
  echo "[失败] 前端 JavaScript 语法检查失败。" >&2
  exit 1
fi
if ! node --test tests/frontend/*.test.mjs >"$RESULTS_DIR/node-tests.log" 2>&1; then
  cat "$RESULTS_DIR/node-tests.log" >&2
  echo "[失败] 前端 Node.js 单元测试失败。" >&2
  exit 1
fi

echo "[通过] bili_workspace v0.7.0 源码自检完成。"
