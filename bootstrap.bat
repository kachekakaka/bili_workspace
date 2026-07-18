@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo [错误] 当前 Windows 未找到 PowerShell，无法解压仓库内置运行时。
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\bootstrap_portable.ps1" %*
exit /b %ERRORLEVEL%
