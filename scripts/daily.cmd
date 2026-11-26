@echo off
REM DSHQuant daily chain wrapper (scheduled task entry).
REM Runs scripts\daily_run.py with the project venv; extra args are forwarded
REM (e.g. "daily.cmd --skip-etf" for a quicker manual run).
cd /d "%~dp0.."
".venv\Scripts\python.exe" -X utf8 "scripts\daily_run.py" --scheduled %*
