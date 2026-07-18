@echo off
chcp 65001 >nul
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
title bili_workspace - B站命令行登录

call "%ROOT%\scripts\windows\prepare-runtime.bat" -Quiet
if errorlevel 1 goto :failed

cd /d "%ROOT%\BBDown_portable"
if not exist "BBDown.exe" (
  echo [错误] 缺少 BBDown.exe。
  goto :failed
)
if not exist "ffmpeg\bin\ffmpeg.exe" (
  echo [错误] 缺少 ffmpeg.exe。
  goto :failed
)

set "PATH=%CD%\ffmpeg\bin;%PATH%"
echo 推荐优先在网站“账号”页面扫码登录。
echo 此命令行备用方式会把凭据保存在 BBDown_portable\BBDown.data。
echo 请勿把登录后的目录或 BBDown.data 发给其他人。
echo.
BBDown.exe login
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" echo 登录命令已结束，可运行 start.bat 后在设置页点击“重新验证登录”。
pause
exit /b %RC%

:failed
echo [错误] B站命令行登录未能启动。
pause
exit /b 1
