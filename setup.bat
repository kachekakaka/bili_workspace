@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.6 - Setup

if exist "vendor\windows\runtime-manifest.json" (
  echo [1/2] Preparing repository-integrated Windows runtime...
  call bootstrap.bat
  if errorlevel 1 goto :failed
  set "PY=.runtime\python\python.exe"
  goto :configure
)

echo [兼容模式] 当前提交尚未包含集成运行时，使用本机 Python 环境。
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11) do (
    if not defined PY_CMD (
      py -%%V -c "import struct; raise SystemExit(0 if struct.calcsize('P')*8==64 else 1)" >nul 2>nul
      if not errorlevel 1 set "PY_CMD=py -%%V"
    )
  )
)
if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import struct,sys; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<=(3,13) and struct.calcsize('P')*8==64 else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
  )
)
if not defined PY_CMD (
  echo [错误] 当前提交没有集成运行时，且未找到 64 位 Python 3.11-3.13。
  goto :failed
)

%PY_CMD% -m tools.bootstrap_windows_runtime
if errorlevel 1 goto :failed
if not exist ".venv\Scripts\python.exe" (
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :failed
)
set "PY=.venv\Scripts\python.exe"
set "PIP_ARGS=--disable-pip-version-check --timeout 120 --retries 10"
if exist "wheelhouse\*.whl" (
  "%PY%" -m pip install %PIP_ARGS% --no-index --find-links "wheelhouse" -r requirements.lock
) else (
  "%PY%" -m pip install %PIP_ARGS% -r requirements.lock
)
if errorlevel 1 goto :failed
"%PY%" -m pip check
if errorlevel 1 goto :failed

:configure
echo [2/2] Creating or upgrading runtime configuration...
"%PY%" -m tools.config_sync
if errorlevel 1 goto :failed

echo.
echo ===== v0.5.6 环境已就绪 =====
echo 以后 git pull 后可直接运行 start.bat；无需重新安装 Python 或下载依赖。
exit /b 0

:failed
echo.
echo ===== 环境准备失败，请查看上方信息 =====
pause
exit /b 1
