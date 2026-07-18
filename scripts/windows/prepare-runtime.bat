@echo off
chcp 65001 >nul
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

if not exist "%ROOT%\vendor\windows\runtime-manifest.json" (
  echo [错误] 当前源码不完整：缺少 vendor\windows\runtime-manifest.json。
  echo 请重新执行 git pull --ff-only origin main，确保两个运行包和清单都已拉取。
  exit /b 1
)

call "%ROOT%\scripts\windows\bootstrap-runtime.bat" %*
if errorlevel 1 exit /b 1

set "PY=%ROOT%\.runtime\python\python.exe"
if not exist "%PY%" (
  echo [错误] 内置 Python 未正确解压：%PY%
  exit /b 1
)

"%PY%" -m tools.config_sync
if errorlevel 1 exit /b 1
exit /b 0
