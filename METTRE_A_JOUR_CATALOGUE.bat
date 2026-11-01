@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Installe d'abord les dependances avec scripts\install_windows.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\update_catalogue.py
pause
