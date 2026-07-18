@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.4 - 完整自检

if not exist ".venv\Scripts\python.exe" (
  call setup.bat
  if errorlevel 1 exit /b 1
)
set "PY=.venv\Scripts\python.exe"
set "SMOKE_DIR=%TEMP%\bili_workspace_verify_%RANDOM%_%RANDOM%"
set "TOOLS_AVAILABLE=1"
if not exist "BBDown_portable\BBDown.exe" set "TOOLS_AVAILABLE=0"
if not exist "BBDown_portable\ffmpeg\bin\ffmpeg.exe" set "TOOLS_AVAILABLE=0"
set "RELEASE_MODE=0"
if exist "RELEASE_MANIFEST.sha256" if "%TOOLS_AVAILABLE%"=="1" set "RELEASE_MODE=1"
mkdir "%SMOKE_DIR%" >nul 2>nul

echo [准备] 创建或升级本地配置...
"%PY%" -m tools.config_sync
if errorlevel 1 goto :failed

echo [1/6] 校验目录结构和敏感信息边界...
if "%RELEASE_MODE%"=="1" (
  "%PY%" tools\verify_package.py
) else (
  echo [源码模式] 未包含发布清单或 Windows 第三方二进制，执行源码仓库校验。
  "%PY%" tools\verify_source.py
)
if errorlevel 1 goto :failed


echo [2/6] Windows 第三方工具冒烟测试...
if "%TOOLS_AVAILABLE%"=="1" (
  "BBDown_portable\BBDown.exe" --help > "%SMOKE_DIR%\bbdown.txt" 2>&1
  if errorlevel 1 (
    echo [错误] BBDown.exe 无法正常启动。输出：
    type "%SMOKE_DIR%\bbdown.txt"
    goto :failed
  )
  for %%F in ("%SMOKE_DIR%\bbdown.txt") do if %%~zF LSS 5 (
    echo [错误] BBDown.exe 已退出，但没有产生有效帮助输出。
    goto :failed
  )
  "BBDown_portable\ffmpeg\bin\ffmpeg.exe" -hide_banner -version > "%SMOKE_DIR%\ffmpeg.txt" 2>&1
  if errorlevel 1 (
    echo [错误] ffmpeg.exe 无法正常启动。输出：
    type "%SMOKE_DIR%\ffmpeg.txt"
    goto :failed
  )
  findstr /I /C:"ffmpeg version" "%SMOKE_DIR%\ffmpeg.txt" >nul
  if errorlevel 1 (
    echo [错误] FFmpeg 输出中未识别到版本信息。
    type "%SMOKE_DIR%\ffmpeg.txt"
    goto :failed
  )
  echo [通过] BBDown 与 FFmpeg 均可在当前 Windows 环境启动。
) else (
  echo [跳过] Windows 工具未就绪；重新运行 setup.bat 可从 Release 运行包安装。
)


echo [3/6] 编译 Python 源码...
"%PY%" -m compileall -q app tests tools docker
if errorlevel 1 goto :failed


echo [4/6] 运行 Ruff 静态检查...
"%PY%" -m ruff check --no-cache app tests tools docker
if errorlevel 1 goto :failed


echo [5/6] 运行完整回归测试...
"%PY%" -m pytest -q -p no:cacheprovider
if errorlevel 1 goto :failed


echo [6/6] 检查前端 JavaScript（未安装 Node.js 时跳过）...
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
echo ===== v0.5.4 自检全部通过 =====
if "%TOOLS_AVAILABLE%"=="1" (
  echo Windows 运行工具已就绪，可运行 start.bat。
) else (
  echo 当前为媒体库源码模式；运行 setup.bat 或按 BBDown_portable\README.md 补齐工具。
)
echo QNAP 部署请阅读 docs\QNAP_Docker部署指南.md。
pause
exit /b 0

:failed
if exist "%SMOKE_DIR%" rmdir /s /q "%SMOKE_DIR%"
echo.
echo ===== 自检失败，请查看上方信息 =====
pause
exit /b 1
