@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "NODE_CHECK_SKIPPED=0"
cd /d "%~dp0"
title bili_workspace v0.7.0 - Windows 部署自检

call "%~dp0scripts\windows\prepare-runtime.bat" -Quiet
if errorlevel 1 goto :failed
set "PY=%~dp0.runtime\python\python.exe"
set "SMOKE_DIR=%TEMP%\bili_workspace_verify_%RANDOM%_%RANDOM%"
mkdir "%SMOKE_DIR%" >nul 2>nul

"%PY%" tools\verify_source.py
if errorlevel 1 goto :failed

"BBDown_portable\BBDown.exe" --help > "%SMOKE_DIR%\bbdown.txt" 2>&1
if errorlevel 1 goto :failed
"BBDown_portable\ffmpeg\bin\ffmpeg.exe" -hide_banner -version > "%SMOKE_DIR%\ffmpeg.txt" 2>&1
if errorlevel 1 goto :failed
findstr /I /C:"ffmpeg version" "%SMOKE_DIR%\ffmpeg.txt" >nul
if errorlevel 1 goto :failed
echo [通过] 内置 Python、BBDown 与 FFmpeg 均可启动。

"%PY%" -m compileall -q app tests tools docker
if errorlevel 1 goto :failed
"%PY%" -m ruff check --no-cache app tests tools docker
if errorlevel 1 goto :failed
"%PY%" -m pytest -q -p no:cacheprovider
if errorlevel 1 goto :failed

where node >nul 2>nul
if errorlevel 1 (
  if /I "%BILI_VERIFY_REQUIRE_NODE%"=="1" (
    echo [阻断] 严格验证要求 Node.js，但当前环境未检测到 node。
    goto :failed
  )
  set "NODE_CHECK_SKIPPED=1"
  echo [提示] 未检测到 Node.js；跳过仅用于开发和发布的前端语法与单元测试。
) else (
  for /r "web" %%F in (*.js) do (
    node --check "%%F"
    if errorlevel 1 goto :failed
  )
  for /r "web" %%F in (*.mjs) do (
    node --check "%%F"
    if errorlevel 1 goto :failed
  )
  for %%F in ("tests\frontend\*.test.mjs") do (
    node --test "%%~fF"
    if errorlevel 1 goto :failed
  )
)

if exist "%SMOKE_DIR%" rmdir /s /q "%SMOKE_DIR%"
echo.
if "%NODE_CHECK_SKIPPED%"=="1" (
  echo ===== v0.7.0 Windows 部署自检通过 =====
  echo 前端开发检查未执行；这不影响应用部署运行。
) else (
  echo ===== v0.7.0 Windows 部署自检全部通过 =====
)
echo 可直接运行 start.bat。
if /I "%BILI_VERIFY_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

:failed
if defined SMOKE_DIR if exist "%SMOKE_DIR%" rmdir /s /q "%SMOKE_DIR%"
echo.
echo ===== 自检失败，请查看上方信息 =====
if /I "%BILI_VERIFY_NO_PAUSE%"=="1" exit /b 1
pause
exit /b 1
