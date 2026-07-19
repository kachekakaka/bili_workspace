@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace - GitHub 更新

where git >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Git。请先安装 Git for Windows。
  pause
  exit /b 1
)

git diff --quiet -- .
if errorlevel 1 goto :dirty
git diff --cached --quiet -- .
if errorlevel 1 goto :dirty

echo [1/3] 拉取 main 分支更新...
git pull --ff-only origin main
if errorlevel 1 goto :failed

echo [2/3] 准备运行时并执行完整自检...
set "BILI_VERIFY_NO_PAUSE=1"
call verify.bat
set "VERIFY_RC=%ERRORLEVEL%"
set "BILI_VERIFY_NO_PAUSE="
if not "%VERIFY_RC%"=="0" goto :failed

echo [3/3] 关闭旧服务并启动当前版本...
start "" "%~dp0start.bat"
exit /b 0

:dirty
echo [错误] 当前目录存在未提交的受 Git 管理修改。为避免覆盖，请先处理这些修改。
git status --short
pause
exit /b 1

:failed
echo [错误] 更新失败，请查看上方信息。
pause
exit /b 1
