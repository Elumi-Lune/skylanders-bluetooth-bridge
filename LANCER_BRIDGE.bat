@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Dependances absentes. Lance d'abord scripts\install_windows.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" src\skylanders_virtport_live.py %*
if errorlevel 1 pause
