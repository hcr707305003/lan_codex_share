@echo off
setlocal
set "DESKTOP_PYTHON=%~dp0.venv-desktop\Scripts\python.exe"
if not exist "%DESKTOP_PYTHON%" (
  echo Desktop environment missing. See README: install requirements-desktop.txt in .venv-desktop using CPython.
  pause
  exit /b 2
)
set "PYTHONUTF8=1"
"%DESKTOP_PYTHON%" "%~dp0run_lan_codex_desktop.py" %*
if errorlevel 1 pause
