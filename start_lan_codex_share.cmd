@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv. Run:
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

if not exist "lan_config.toml" (
  echo [ERROR] Missing lan_config.toml. Copy lan_config.example.toml and check workspace.
  pause
  exit /b 2
)

".venv\Scripts\python.exe" -m lan_codex_share --config lan_config.toml
set "SHARE_EXIT=%ERRORLEVEL%"
if not "%SHARE_EXIT%"=="0" (
  echo.
  echo LAN Shared Codex Session exited with code %SHARE_EXIT%.
  pause
)
exit /b %SHARE_EXIT%
