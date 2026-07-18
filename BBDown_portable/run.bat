@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PATH=%CD%\ffmpeg\bin;%PATH%"
BBDown.exe %*
exit /b %ERRORLEVEL%
