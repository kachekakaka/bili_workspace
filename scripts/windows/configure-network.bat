@echo off
chcp 65001 >nul
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
title bili_workspace - 网络配置

call "%ROOT%\scripts\windows\prepare-runtime.bat" -Quiet
if errorlevel 1 goto :failed

"%ROOT%\.runtime\python\python.exe" -m tools.configure_network
if errorlevel 1 goto :failed
exit /b 0

:failed
echo [错误] 网络配置未完成，请查看上方信息。
pause
exit /b 1
