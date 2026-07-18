@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.3

if not exist ".venv\Scripts\python.exe" (
  call setup.bat
  if errorlevel 1 exit /b 1
)
set "PY=.venv\Scripts\python.exe"

"%PY%" -m tools.config_sync
if errorlevel 1 goto :failed

for /f "tokens=1,* delims==" %%A in ('"%PY%" -m tools.start_info --machine') do set "%%A=%%B"
if not defined OPEN_URL set "OPEN_URL=http://127.0.0.1:3398/"

echo 启动地址：%BIND_HOST%:%BIND_PORT%
if "%SERVER_MODE%"=="1" (
  echo 已启用服务器模式和管理员认证；手机请访问电脑的局域网 IP 加端口。
) else (
  echo 当前只允许本机访问。
)
echo 按 Ctrl+C 停止。
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%OPEN_URL%'"
"%PY%" -m app
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%

:failed
echo [错误] 启动前配置同步失败。
pause
exit /b 1
