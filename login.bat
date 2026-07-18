@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace - B站登录

if exist "vendor\windows\runtime-manifest.json" (
  call bootstrap.bat -Quiet
  if errorlevel 1 exit /b 1
) else (
  if not exist "BBDown_portable\BBDown.exe" (
    call setup.bat
    if errorlevel 1 exit /b 1
  )
)

cd /d "%~dp0BBDown_portable"
if not exist "BBDown.exe" (
  echo [错误] 缺少 BBDown.exe。
  pause
  exit /b 1
)
if not exist "ffmpeg\bin\ffmpeg.exe" (
  echo [错误] 缺少 ffmpeg.exe。
  pause
  exit /b 1
)

set "PATH=%CD%\ffmpeg\bin;%PATH%"
echo 登录信息将保存在本机 BBDown_portable\BBDown.data。
echo 请勿把登录后的目录或 BBDown.data 发给其他人。
echo.
BBDown.exe login
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" echo 登录命令已结束，可运行 start.bat 后在设置页点击“重新验证登录”。
pause
exit /b %RC%
