@echo off
REM DSHQuant launcher: project venv first, then bundled Python, then system Python.
REM Source deploy: requirements.txt is installed into .venv, so prefer it over conda/system Python.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launcher.py
  goto :end
)
if exist "runtime\python\python.exe" (
  "runtime\python\python.exe" launcher.py
  goto :end
)
if exist "portable-py\Scripts\python.exe" (
  "portable-py\Scripts\python.exe" launcher.py
  goto :end
)
python launcher.py
:end
pause
