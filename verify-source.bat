@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.4 - 源码自检

set "NEED_SETUP=0"
if not exist ".venv\Scripts\python.exe" set "NEED_SETUP=1"
if "%NEED_SETUP%"=="0" (
  ".venv\Scripts\python.exe" -c "import fastapi,httpx,pydantic,pytest,uvicorn" >nul 2>nul
  if errorlevel 1 set "NEED_SETUP=1"
)
if "%NEED_SETUP%"=="0" (
  ".venv\Scripts\python.exe" -m ruff --version >nul 2>nul
  if errorlevel 1 set "NEED_SETUP=1"
)

if "%NEED_SETUP%"=="1" (
  echo [准备] 创建或修复源码自检 Python 环境；不下载 Windows 媒体运行包。
  set "BILI_SKIP_RUNTIME_DOWNLOAD=1"
  call setup.bat
  if errorlevel 1 exit /b 1
)
set "PY=.venv\Scripts\python.exe"

"%PY%" tools\verify_source.py
if errorlevel 1 goto :failed

"%PY%" -m compileall -q app tests tools docker
if errorlevel 1 goto :failed

"%PY%" -m ruff check --no-cache app tests tools docker
if errorlevel 1 goto :failed

"%PY%" -m pytest -q -p no:cacheprovider
if errorlevel 1 goto :failed

where node >nul 2>nul
if errorlevel 1 (
  echo [跳过] 未检测到 Node.js；其余源码自检不受影响。
) else (
  for /r "web" %%F in (*.js) do (
    node --check "%%F"
    if errorlevel 1 goto :failed
  )
)

echo.
echo ===== v0.5.4 源码自检全部通过 =====
pause
exit /b 0

:failed
echo.
echo ===== 源码自检失败，请查看上方信息 =====
pause
exit /b 1
