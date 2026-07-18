@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title bili_workspace v0.5.4 - Setup

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.13 3.12 3.11) do (
    if not defined PY_CMD (
      py -%%V -c "import struct; raise SystemExit(0 if struct.calcsize('P')*8==64 else 1)" >nul 2>nul
      if not errorlevel 1 set "PY_CMD=py -%%V"
    )
  )
)
if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import struct,sys; raise SystemExit(0 if (3,11)<=sys.version_info[:2]<=(3,13) and struct.calcsize('P')*8==64 else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
  )
)
if not defined PY_CMD (
  echo [ERROR] 64-bit Python 3.11, 3.12, or 3.13 was not found.
  echo Install a supported version with Python Launcher or Add Python to PATH enabled.
  pause
  exit /b 1
)

%PY_CMD% -c "import struct,sys; print('Python',sys.version.split()[0],str(struct.calcsize('P')*8)+'-bit')"
if errorlevel 1 goto :failed

echo [1/4] Preparing verified Windows runtime and offline wheels...
%PY_CMD% -m tools.bootstrap_windows_runtime
if errorlevel 1 goto :failed

if not exist ".venv\Scripts\python.exe" (
  echo [2/4] Creating local virtual environment...
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto :failed
) else (
  echo [2/4] Reusing local virtual environment...
)

set "VENV_PY=.venv\Scripts\python.exe"
echo [3/4] Installing locked Python dependencies...
if exist "wheelhouse" (
  "%VENV_PY%" -m pip install --disable-pip-version-check --no-index --find-links "wheelhouse" -r requirements.lock
  if errorlevel 1 (
    echo [INFO] Offline wheels did not match this Python. Retrying from configured package index...
    "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.lock
  )
) else (
  "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.lock
)
if errorlevel 1 goto :failed
"%VENV_PY%" -m pip check
if errorlevel 1 goto :failed

echo [4/4] Creating or upgrading runtime configuration...
"%VENV_PY%" -m tools.config_sync
if errorlevel 1 goto :failed

echo Setup completed.
echo Run verify.bat for the full self-check, then start.bat.
exit /b 0

:failed
echo [ERROR] Setup failed. Review the message above.
pause
exit /b 1
