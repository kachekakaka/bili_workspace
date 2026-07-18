@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace - 网络配置

if not exist ".venv\Scripts\python.exe" (
  call setup.bat
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m tools.configure_network
if errorlevel 1 pause
