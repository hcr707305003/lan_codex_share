@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Missing .venv.
  pause
  exit /b 1
)

if not exist "lan_config.toml" (
  echo [ERROR] Missing lan_config.toml.
  pause
  exit /b 2
)

".venv\Scripts\python.exe" -m lan_codex_share cli --config lan_config.toml %*
set "CLI_EXIT=%ERRORLEVEL%"
if not "%CLI_EXIT%"=="0" (
  echo.
  echo Shared Codex CLI exited with code %CLI_EXIT%.
  pause
)
exit /b %CLI_EXIT%
