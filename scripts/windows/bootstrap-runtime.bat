@echo off
chcp 65001 >nul
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"

where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo [错误] 当前 Windows 未找到 PowerShell 5.1 或更高版本，无法解压仓库内置运行时。
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\windows\bootstrap-portable.ps1" %*
exit /b %ERRORLEVEL%
