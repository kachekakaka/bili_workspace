@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.3 - 初始化环境

where py >nul 2>nul
if not errorlevel 1 (
  set "PY_CMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [错误] 未找到 Python。请安装 64 位 Python 3.11、3.12 或 3.13，并勾选 Add Python to PATH。
    pause
    exit /b 1
  )
  set "PY_CMD=python"
)

%PY_CMD% -c "import struct,sys; ok=(3,11)<=sys.version_info[:2]<=(3,13) and struct.calcsize('P')*8==64; print('Python',sys.version.split()[0],str(struct.calcsize('P')*8)+'-bit'); raise SystemExit(0 if ok else 1)"
if errorlevel 1 (
  echo [错误] 需要 64 位 Python 3.11、3.12 或 3.13。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 创建本地虚拟环境...
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :failed
)

set "VENV_PY=.venv\Scripts\python.exe"
echo [2/3] 安装固定版本依赖...
if exist "wheelhouse" (
  "%VENV_PY%" -m pip install --disable-pip-version-check --no-index --find-links "wheelhouse" -r requirements.lock
  if errorlevel 1 (
    echo [提示] 离线依赖与当前 Python 不匹配，改用在线源安装...
    "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.lock
  )
) else (
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.lock
)
if errorlevel 1 goto :failed

"%VENV_PY%" -m pip check
if errorlevel 1 goto :failed

echo [3/3] 创建或升级本地配置...
"%VENV_PY%" -m tools.config_sync
if errorlevel 1 goto :failed

echo 环境初始化完成。
echo Run verify.bat for full self-check, or start.bat to launch the website.
exit /b 0

:failed
echo [错误] 初始化失败，请查看上方错误信息。
pause
exit /b 1
