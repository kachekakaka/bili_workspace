@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [信息] 未找到项目环境，开始初始化...
  call setup.bat
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" launcher.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo ===== 启动失败，请查看上方信息 =====
pause
exit /b 1
