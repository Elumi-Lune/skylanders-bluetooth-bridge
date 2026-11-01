@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
  echo Python est introuvable. Installe Python 3.10+ depuis python.org, puis reessaie.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :fail
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo.
echo Installation terminee. Lance LANCER_BRIDGE.bat.
pause
exit /b 0
:fail
echo ERREUR installation. Verifie la connexion Internet et Python.
pause
exit /b 1
