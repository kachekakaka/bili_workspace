@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.6 - 完整自检

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
  echo [跳过] 未检测到 Node.js；其余自检不受影响。
) else (
  for /r "web" %%F in (*.js) do (
    node --check "%%F"
    if errorlevel 1 goto :failed
  )
)

if exist "%SMOKE_DIR%" rmdir /s /q "%SMOKE_DIR%"
echo.
echo ===== v0.5.6 自检全部通过 =====
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
