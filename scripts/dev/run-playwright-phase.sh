#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON:-python3}"
BROWSER_OVERRIDE="${BILI_PLAYWRIGHT_CHROMIUM:-}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[阻断] T-PROJECT 浏览器阶段要求 Python。" >&2
  exit 1
fi

if ! RUN_ROOT=$("$PYTHON_BIN" -B -X utf8 tools/t_project_isolation.py create --workspace-root "$ROOT"); then
  echo "[阻断] 无法创建 T-PROJECT 浏览器阶段隔离运行目录。" >&2
  exit 1
fi
RESULTS_DIR="$RUN_ROOT/results"
FINALIZED=0

record_result() {
  status="$1"
  exit_code="$2"
  message="$3"
  "$PYTHON_BIN" -B -X utf8 tools/t_project_isolation.py record \
    --workspace-root "$ROOT" \
    --run-root "$RUN_ROOT" \
    --status "$status" \
    --exit-code "$exit_code" \
    --message "$message" >"$RESULTS_DIR/result-record.log" 2>&1
  FINALIZED=1
}

finish() {
  code=$?
  trap - EXIT HUP INT TERM
  if [ "$FINALIZED" -ne 1 ]; then
    "$PYTHON_BIN" -B -X utf8 tools/t_project_isolation.py record \
      --workspace-root "$ROOT" \
      --run-root "$RUN_ROOT" \
      --status inconclusive \
      --exit-code "$code" \
      --message "T-PROJECT 浏览器阶段提前结束，未能判定完整结果。" \
      >>"$RESULTS_DIR/result-record.log" 2>&1 || true
  fi
  if [ "$code" -ne 0 ]; then
    echo "运行资产已保留在：$RUN_ROOT" >&2
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
export BILI_RUN_PLAYWRIGHT=1
unset BILI_DATABASE_PATH
mkdir -p "$BILI_CACHE_DIR"

if [ -n "$BROWSER_OVERRIDE" ]; then
  export BILI_PLAYWRIGHT_CHROMIUM="$BROWSER_OVERRIDE"
else
  unset BILI_PLAYWRIGHT_CHROMIUM
fi

if ! "$PYTHON_BIN" -B -X utf8 -c 'import playwright,pytest' >"$RESULTS_DIR/python-dependencies.log" 2>&1; then
  record_result blocked 1 "T-PROJECT 浏览器阶段缺少 Playwright 或 pytest。"
  cat "$RESULTS_DIR/python-dependencies.log" >&2
  exit 1
fi

if "$PYTHON_BIN" -B -X utf8 tools/playwright_runtime.py \
  --workspace-root "$ROOT" \
  --run-root "$RUN_ROOT" \
  --probe >"$RESULTS_DIR/playwright-browser.path" 2>"$RESULTS_DIR/playwright-runtime.log"; then
  if ! IFS= read -r BILI_PLAYWRIGHT_CHROMIUM <"$RESULTS_DIR/playwright-browser.path" || [ -z "$BILI_PLAYWRIGHT_CHROMIUM" ]; then
    record_result inconclusive 1 "浏览器运行器未返回可用路径。"
    echo "[不确定] 浏览器运行器未返回可用路径。" >&2
    exit 1
  fi
  export BILI_PLAYWRIGHT_CHROMIUM
else
  playwright_exit=$?
  cat "$RESULTS_DIR/playwright-runtime.log" >&2
  if [ "$playwright_exit" -eq 3 ]; then
    record_result blocked 1 "T-PROJECT 浏览器阶段缺少可用的既有 Playwright 浏览器。"
  else
    record_result inconclusive 1 "T-PROJECT 浏览器运行器异常。"
  fi
  exit 1
fi

if ! "$PYTHON_BIN" -B -X utf8 -m pytest \
  -q -p no:cacheprovider --tb=short \
  --basetemp "$RUN_ROOT/tmp/pytest" \
  -m playwright >"$RESULTS_DIR/playwright-tests.log" 2>&1; then
  record_result failed 1 "T-PROJECT Playwright 断言失败。"
  cat "$RESULTS_DIR/playwright-tests.log" >&2
  exit 1
fi

record_result passed 0 "T-PROJECT Playwright 浏览器阶段全部通过。"
echo "[通过] T-PROJECT Playwright 浏览器阶段完成。"
echo "运行资产已保留在：$RUN_ROOT"
