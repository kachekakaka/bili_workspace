@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
title bili_workspace v0.6.1

call "%~dp0scripts\windows\prepare-runtime.bat" -Quiet
if errorlevel 1 goto :failed
set "PY=%~dp0.runtime\python\python.exe"

for /f "tokens=1,* delims==" %%A in ('"%PY%" -m tools.start_info --machine') do set "%%A=%%B"
if not defined OPEN_URL set "OPEN_URL=http://127.0.0.1:3398/"
if not defined BIND_PORT set "BIND_PORT=3398"
set "BROWSER_URL=%OPEN_URL%?fresh=%RANDOM%-%RANDOM%"

"%PY%" -m tools.server_instance --url "%OPEN_URL%" --port "%BIND_PORT%"
set "INSTANCE_RC=%ERRORLEVEL%"
if "%INSTANCE_RC%"=="10" (
  start "" "%BROWSER_URL%"
  exit /b 0
)
if not "%INSTANCE_RC%"=="0" goto :instance_failed

echo 启动地址：%BIND_HOST%:%BIND_PORT%
if "%SERVER_MODE%"=="1" (
  echo 已启用服务器模式和管理员认证；手机请访问电脑的局域网 IP 加端口。
) else (
  echo 当前只允许本机访问。
)
echo 按 Ctrl+C 停止。
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%BROWSER_URL%'"
"%PY%" -m app
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%

:instance_failed
echo [错误] 未能准备当前服务实例。浏览器不会再自动打开旧服务。
pause
exit /b %INSTANCE_RC%

:failed
echo [错误] 启动前运行时或配置准备失败。
pause
exit /b 1
