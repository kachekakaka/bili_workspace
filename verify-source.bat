@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.6 - 源码自检

if exist "vendor\windows\runtime-manifest.json" (
  call bootstrap.bat -Quiet
  if errorlevel 1 exit /b 1
  set "PY=.runtime\python\python.exe"
) else (
  set "NEED_SETUP=0"
  if not exist ".venv\Scripts\python.exe" set "NEED_SETUP=1"
  if "%NEED_SETUP%"=="0" (
    ".venv\Scripts\python.exe" -c "import fastapi,httpx,pydantic,pytest,uvicorn" >nul 2>nul
    if errorlevel 1 set "NEED_SETUP=1"
  )
  if "%NEED_SETUP%"=="1" (
    set "BILI_SKIP_RUNTIME_DOWNLOAD=1"
    call setup.bat
    if errorlevel 1 exit /b 1
  )
  set "PY=.venv\Scripts\python.exe"
)

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
echo ===== v0.5.6 源码自检全部通过 =====
pause
exit /b 0

:failed
echo.
echo ===== 源码自检失败，请查看上方信息 =====
pause
exit /b 1
