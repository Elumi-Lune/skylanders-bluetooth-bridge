@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Installe d'abord les dependances avec scripts\install_windows.bat
  pause
  exit /b 1
)
echo.
echo ATTENTION : le paquet vgamepad peut demander l'installation du pilote tiers ViGEmBus.
echo Ce pilote est ancien et son projet n'est plus maintenu. Lis docs\MANETTE_FR.md.
echo Rien ne sera installe sans ta confirmation.
choice /M "Installer vgamepad et accepter l'eventuelle demande du pilote"
if errorlevel 2 exit /b 0
".venv\Scripts\python.exe" -m pip install "vgamepad>=0.1,<1"
pause
