@echo off
REM Stop DSHQuant local services (deck :8787 / HARNESS :3080)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\stop_services.ps1"
pause
