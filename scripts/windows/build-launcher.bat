@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\..\.."

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [错误] 缺少仓库统一 Python 3.11 环境：%PYTHON% 1>&2
  exit /b 1
)
"%PYTHON%" -B -X utf8 -m tools.build_launcher --run-exe-self-check %*
exit /b %ERRORLEVEL%
