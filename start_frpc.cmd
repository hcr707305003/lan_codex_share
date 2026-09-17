@echo off
setlocal
set "FRPC_CONFIG=%~1"
if not defined FRPC_CONFIG set "FRPC_CONFIG=%~dp0frpc.toml"
if not "%~2"=="" (
  echo Usage: start_frpc.cmd [frpc-config.toml]
  exit /b 2
)
if not exist "%FRPC_CONFIG%" (
  echo [ERROR] Missing frpc config. Copy frpc.example.toml to frpc.toml and edit it.
  exit /b 2
)
set "FRPC_EXEC="
if exist "%~dp0frpc.exe" set "FRPC_EXEC=%~dp0frpc.exe"
if not defined FRPC_EXEC (
  for /f "delims=" %%I in ('where frpc.exe 2^>nul') do if not defined FRPC_EXEC set "FRPC_EXEC=%%I"
)
if not defined FRPC_EXEC (
  echo [ERROR] Install frpc.exe beside this script or on PATH. Start Share separately.
  exit /b 1
)
"%FRPC_EXEC%" -c "%FRPC_CONFIG%"
exit /b %ERRORLEVEL%
