@echo off
setlocal
cd /d "%~dp0"
title HexInfinite Solver Launcher

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
set "LAUNCH_EXIT=%ERRORLEVEL%"

if not "%LAUNCH_EXIT%"=="0" (
  echo.
  echo [ERROR] Launcher failed with exit code %LAUNCH_EXIT%.
  echo See the message above, then press any key to close this window.
  pause >nul
)

exit /b %LAUNCH_EXIT%
