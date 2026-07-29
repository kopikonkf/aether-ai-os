@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_AETHER_WINDOWS_ALPHA.ps1" -Action Pulse
exit /b %errorlevel%
