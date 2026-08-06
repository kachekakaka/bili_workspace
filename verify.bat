@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "PSModuleAnalysisCachePath=NUL"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "NODE_CHECK_SKIPPED=0"
set "FAIL_STATUS=failed"
set "FAIL_MESSAGE=验证命令失败。"
cd /d "%~dp0"
title bili_workspace v0.7.0 - Windows 部署自检

set "VERIFY_RUN="
for /f "usebackq delims=" %%I in (`powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\new-test-run.ps1" -Action Create`) do if not defined VERIFY_RUN set "VERIFY_RUN=%%I"
if not defined VERIFY_RUN goto :setup_failed

set "RESULTS_DIR=%VERIFY_RUN%\results"
set "PY=%VERIFY_RUN%\runtime\python\python.exe"
set "BBDOWN=%VERIFY_RUN%\media\BBDown_portable\BBDown.exe"
set "FFMPEG=%VERIFY_RUN%\media\BBDown_portable\ffmpeg\bin\ffmpeg.exe"
set "BILI_VERIFY_RUN_ROOT=%VERIFY_RUN%"
set "BILI_VERIFY_ROOT_ENV_PATH=%VERIFY_RUN%\config\root.env"
set "BILI_APP_MODE=local"
set "BILI_CONFIG_DIR=%VERIFY_RUN%\config"
set "BILI_USERDATA_DIR=%VERIFY_RUN%\userdata"
set "BILI_MEDIA_DIR=%VERIFY_RUN%\downloads"
set "BILI_CACHE_DIR=%VERIFY_RUN%\userdata\cache"
set "BILI_TEMP_DIR=%VERIFY_RUN%\tmp"
set "BILI_BBDOWN_DIR=%VERIFY_RUN%\media\BBDown_portable"
set "HOME=%VERIFY_RUN%\home"
set "USERPROFILE=%VERIFY_RUN%\home"
set "XDG_CACHE_HOME=%VERIFY_RUN%\userdata\cache"
set "PYTHONPYCACHEPREFIX=%VERIFY_RUN%\pycache"
set "TEMP=%VERIFY_RUN%\tmp"
set "TMP=%VERIFY_RUN%\tmp"
mkdir "%BILI_CACHE_DIR%" >nul 2>nul

where node >nul 2>nul
if errorlevel 1 (
  if /I "%BILI_VERIFY_REQUIRE_NODE%"=="1" (
    set "FAIL_STATUS=blocked"
    set "FAIL_MESSAGE=严格验证要求 Node.js，但当前环境未检测到 node。"
    echo [阻断] 严格验证要求 Node.js，但当前环境未检测到 node。
    goto :failed
  )
  set "NODE_CHECK_SKIPPED=1"
  echo [提示] 未检测到 Node.js；跳过仅用于开发和发布的前端语法与单元测试。
)

if not exist "%~dp0vendor\windows\runtime-manifest.json" (
  set "FAIL_STATUS=blocked"
  set "FAIL_MESSAGE=缺少 Windows 集成运行时清单。"
  goto :failed
)
if not exist "%~dp0vendor\windows\python-runtime.pack" (
  set "FAIL_STATUS=blocked"
  set "FAIL_MESSAGE=缺少内置 Python 运行包。"
  goto :failed
)
if not exist "%~dp0vendor\windows\media-runtime.pack" (
  set "FAIL_STATUS=blocked"
  set "FAIL_MESSAGE=缺少内置 BBDown 或 FFmpeg 运行包。"
  goto :failed
)

set "FAIL_MESSAGE=集成 Windows 运行时准备失败。"
call "%~dp0scripts\windows\bootstrap-runtime.bat" -Quiet -VerificationRunRoot "%VERIFY_RUN%" > "%RESULTS_DIR%\bootstrap-runtime.log" 2>&1
if errorlevel 1 (
  type "%RESULTS_DIR%\bootstrap-runtime.log"
  goto :failed
)

set "FAIL_MESSAGE=隔离配置同步失败。"
"%PY%" -m tools.config_sync > "%RESULTS_DIR%\config-sync.log" 2>&1
if errorlevel 1 (
  type "%RESULTS_DIR%\config-sync.log"
  goto :failed
)

set "FAIL_MESSAGE=源码结构检查失败。"
"%PY%" tools\verify_source.py > "%RESULTS_DIR%\verify-source.log" 2>&1
if errorlevel 1 (
  type "%RESULTS_DIR%\verify-source.log"
  goto :failed
)

set "FAIL_MESSAGE=BBDown 冒烟测试失败。"
"%BBDOWN%" --help > "%RESULTS_DIR%\bbdown.log" 2>&1
if errorlevel 1 goto :failed
set "FAIL_MESSAGE=FFmpeg 冒烟测试失败。"
"%FFMPEG%" -hide_banner -version > "%RESULTS_DIR%\ffmpeg.log" 2>&1
if errorlevel 1 goto :failed
findstr /I /C:"ffmpeg version" "%RESULTS_DIR%\ffmpeg.log" >nul
if errorlevel 1 goto :failed
echo [通过] 内置 Python、BBDown 与 FFmpeg 均可启动。

set "FAIL_MESSAGE=Python 编译检查失败。"
"%PY%" -m compileall -q app tests tools docker > "%RESULTS_DIR%\compileall.log" 2>&1
if errorlevel 1 (
  type "%RESULTS_DIR%\compileall.log"
  goto :failed
)
set "FAIL_MESSAGE=Ruff 检查失败。"
"%PY%" -m ruff check --no-cache app tests tools docker > "%RESULTS_DIR%\ruff.log" 2>&1
if errorlevel 1 (
  type "%RESULTS_DIR%\ruff.log"
  goto :failed
)
set "FAIL_MESSAGE=Pytest 检查失败。"
setlocal
set "BILI_VERIFY_RUN_ROOT="
set "BILI_VERIFY_ROOT_ENV_PATH="
set "BILI_APP_MODE="
set "BILI_CONFIG_DIR="
set "BILI_USERDATA_DIR="
set "BILI_DATABASE_PATH="
set "BILI_MEDIA_DIR="
set "BILI_CACHE_DIR="
set "BILI_TEMP_DIR="
set "BILI_BBDOWN_DIR="
"%PY%" -m pytest -q -p no:cacheprovider --basetemp "%VERIFY_RUN%\pytest" > "%RESULTS_DIR%\pytest.log" 2>&1
set "PYTEST_EXIT=%ERRORLEVEL%"
endlocal & set "PYTEST_EXIT=%PYTEST_EXIT%"
if not "%PYTEST_EXIT%"=="0" (
  type "%RESULTS_DIR%\pytest.log"
  goto :failed
)

if "%NODE_CHECK_SKIPPED%"=="0" (
  type nul > "%RESULTS_DIR%\node-syntax.log"
  set "FAIL_MESSAGE=前端 JavaScript 语法检查失败。"
  for /r "web" %%F in (*.js) do (
    node --check "%%F" >> "%RESULTS_DIR%\node-syntax.log" 2>&1
    if errorlevel 1 goto :failed
  )
  for /r "web" %%F in (*.mjs) do (
    node --check "%%F" >> "%RESULTS_DIR%\node-syntax.log" 2>&1
    if errorlevel 1 goto :failed
  )
  set "FAIL_MESSAGE=前端 Node.js 单元测试失败。"
  type nul > "%RESULTS_DIR%\node-tests.log"
  for %%F in ("tests\frontend\*.test.mjs") do (
    node --test "%%~fF" >> "%RESULTS_DIR%\node-tests.log" 2>&1
    if errorlevel 1 goto :failed
  )
)

if "%NODE_CHECK_SKIPPED%"=="1" (
  call :record_result passed 0 "部署自检通过；Node.js 开发检查未执行。"
) else (
  call :record_result passed 0 "部署自检全部通过。"
)
echo.
if "%NODE_CHECK_SKIPPED%"=="1" (
  echo ===== v0.7.0 Windows 部署自检通过 =====
  echo 前端开发检查未执行；这不影响应用部署运行。
) else (
  echo ===== v0.7.0 Windows 部署自检全部通过 =====
)
echo 可直接运行 start.bat。
echo 运行资产已保留在：%VERIFY_RUN%
if /I "%BILI_VERIFY_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

:record_result
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\new-test-run.ps1" -Action Record -RunRoot "%VERIFY_RUN%" -Status "%~1" -ExitCode %~2 -Message "%~3" > "%RESULTS_DIR%\result-record.log" 2>&1
if errorlevel 1 (
  echo [警告] 无法写入 T-PROJECT 最终结果，请检查：%RESULTS_DIR%\result-record.log
)
exit /b 0

:setup_failed
echo.
echo ===== 无法创建 T-PROJECT 隔离运行目录 =====
echo 已有测试根目录必须带有匹配的所有权标记，且不得与仓库互相包含。
if /I "%BILI_VERIFY_NO_PAUSE%"=="1" exit /b 1
pause
exit /b 1

:failed
call :record_result %FAIL_STATUS% 1 "%FAIL_MESSAGE%"
echo.
echo ===== 自检未通过：%FAIL_MESSAGE% =====
echo 运行资产已保留在：%VERIFY_RUN%
if /I "%BILI_VERIFY_NO_PAUSE%"=="1" exit /b 1
pause
exit /b 1
