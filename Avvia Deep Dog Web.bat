@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente Python non trovato. Installa prima Deep Dog 2.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" web_app.py
if errorlevel 1 pause
