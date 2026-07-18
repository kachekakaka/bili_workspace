@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace - 网络配置

call setup.bat
if errorlevel 1 exit /b 1
if exist ".runtime\python\python.exe" (
  set "PY=.runtime\python\python.exe"
) else (
  set "PY=.venv\Scripts\python.exe"
)
"%PY%" -m tools.configure_network
if errorlevel 1 pause
