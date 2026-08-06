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

if ! RUN_ROOT=$("$PYTHON_BIN" tools/t_project_isolation.py create --workspace-root "$ROOT"); then
  echo "[阻断] 无法创建 T-PROJECT 仓库外隔离运行目录。" >&2
  exit 1
fi
RESULTS_DIR="$RUN_ROOT/results"
FINALIZED=0

record_result() {
  status="$1"
  exit_code="$2"
  message="$3"
  "$PYTHON_BIN" tools/t_project_isolation.py record \
    --workspace-root "$ROOT" \
    --run-root "$RUN_ROOT" \
    --status "$status" \
    --exit-code "$exit_code" \
    --message "$message" >/dev/null
  FINALIZED=1
}

finish() {
  code=$?
  trap - EXIT HUP INT TERM
  if [ "$FINALIZED" -ne 1 ]; then
    "$PYTHON_BIN" tools/t_project_isolation.py record \
      --workspace-root "$ROOT" \
      --run-root "$RUN_ROOT" \
      --status inconclusive \
      --exit-code "$code" \
      --message "验证进程提前结束，未能判定完整结果。" >/dev/null 2>&1 || true
  fi
  if [ "$code" -ne 0 ]; then
    echo "运行资产已保留在：$RUN_ROOT" >&2
  fi
  exit "$code"
}

trap finish EXIT
trap 'exit 130' HUP INT TERM

export BILI_VERIFY_RUN_ROOT="$RUN_ROOT"
export BILI_VERIFY_ROOT_ENV_PATH="$RUN_ROOT/config/root.env"
export BILI_APP_MODE=local
export BILI_CONFIG_DIR="$RUN_ROOT/config"
export BILI_USERDATA_DIR="$RUN_ROOT/userdata"
export BILI_MEDIA_DIR="$RUN_ROOT/downloads"
export BILI_CACHE_DIR="$RUN_ROOT/userdata/cache"
export BILI_TEMP_DIR="$RUN_ROOT/tmp"
export BILI_BBDOWN_DIR="$RUN_ROOT/media/BBDown_portable"
export HOME="$RUN_ROOT/home"
export XDG_CACHE_HOME="$RUN_ROOT/userdata/cache"
export PYTHONPYCACHEPREFIX="$RUN_ROOT/pycache"
export TMPDIR="$RUN_ROOT/tmp"
mkdir -p "$BILI_CACHE_DIR"

if ! command -v node >/dev/null 2>&1; then
  record_result blocked 1 "T-PROJECT 完整源码自检要求 Node.js。"
  echo "[阻断] T-PROJECT 完整源码自检要求 Node.js。" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import fastapi,httpx,pydantic,pytest,ruff,starlette,uvicorn' >"$RESULTS_DIR/python-dependencies.log" 2>&1; then
  record_result blocked 1 "T-PROJECT 完整源码自检缺少项目锁定的 Python 开发依赖。"
  cat "$RESULTS_DIR/python-dependencies.log" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -m tools.config_sync >"$RESULTS_DIR/config-sync.log" 2>&1; then
  record_result failed 1 "隔离配置同步失败。"
  cat "$RESULTS_DIR/config-sync.log" >&2
  exit 1
fi
if ! "$PYTHON_BIN" tools/verify_source.py >"$RESULTS_DIR/verify-source.log" 2>&1; then
  record_result failed 1 "源码结构检查失败。"
  cat "$RESULTS_DIR/verify-source.log" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -m compileall -q app tests tools docker >"$RESULTS_DIR/compileall.log" 2>&1; then
  record_result failed 1 "Python 编译检查失败。"
  cat "$RESULTS_DIR/compileall.log" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -m ruff check --no-cache app tests tools docker >"$RESULTS_DIR/ruff.log" 2>&1; then
  record_result failed 1 "Ruff 检查失败。"
  cat "$RESULTS_DIR/ruff.log" >&2
  exit 1
fi
if ! (
  unset BILI_VERIFY_RUN_ROOT BILI_VERIFY_ROOT_ENV_PATH BILI_APP_MODE
  unset BILI_CONFIG_DIR BILI_USERDATA_DIR BILI_DATABASE_PATH BILI_MEDIA_DIR
  unset BILI_CACHE_DIR BILI_TEMP_DIR BILI_BBDOWN_DIR
  "$PYTHON_BIN" -m pytest -q -p no:cacheprovider --basetemp "$RUN_ROOT/pytest"
) >"$RESULTS_DIR/pytest.log" 2>&1; then
  record_result failed 1 "Pytest 检查失败。"
  cat "$RESULTS_DIR/pytest.log" >&2
  exit 1
fi

if ! find web -type f \( -name '*.js' -o -name '*.mjs' \) -print0 | sort -z | xargs -0 -n1 node --check >"$RESULTS_DIR/node-syntax.log" 2>&1; then
  record_result failed 1 "前端 JavaScript 语法检查失败。"
  cat "$RESULTS_DIR/node-syntax.log" >&2
  exit 1
fi
if ! node --test tests/frontend/*.test.mjs >"$RESULTS_DIR/node-tests.log" 2>&1; then
  record_result failed 1 "前端 Node.js 单元测试失败。"
  cat "$RESULTS_DIR/node-tests.log" >&2
  exit 1
fi

record_result passed 0 "bili_workspace v0.7.0 源码自检全部通过。"
echo "[通过] bili_workspace v0.7.0 源码自检完成。"
echo "运行资产已保留在：$RUN_ROOT"
