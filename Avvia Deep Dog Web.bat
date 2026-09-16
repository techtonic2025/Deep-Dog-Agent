@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Deep Dog - Installazione e avvio
cd /d "%~dp0"

echo.
echo ========================================================
echo                 DEEP DOG AGENT
echo           Controllo, installazione e avvio
echo ========================================================
echo.

set "PYTHON_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)
if not defined PYTHON_CMD goto install_python
goto python_ready

:install_python
echo [1/4] Python 3.11 o superiore non trovato.
where winget >nul 2>&1
if errorlevel 1 goto no_python_installer
echo Installazione automatica di Python 3.12 tramite winget...
winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto python_install_failed
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"
    goto python_ready
)
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.12"
    goto python_ready
)
goto python_restart_needed

:python_ready
echo [1/4] Python disponibile.
if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creo l'ambiente Python locale...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto venv_failed
) else (
    echo [2/4] Ambiente Python locale gia presente.
)

echo [3/4] Controllo e installo solo i componenti mancanti...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto dependencies_failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto dependencies_failed

echo [4/4] Avvio Deep Dog...
echo Il browser si aprira automaticamente su http://127.0.0.1:8765/
echo Per spegnere Deep Dog chiudi questa finestra o premi Ctrl+C.
echo.
".venv\Scripts\python.exe" web_app.py
if errorlevel 1 goto app_failed
goto end

:no_python_installer
echo.
echo ERRORE: Python non e installato e winget non e disponibile.
echo Installa Python 3.11 o superiore da https://www.python.org/downloads/
echo Durante l'installazione attiva "Add Python to PATH".
goto failure

:python_install_failed
echo.
echo ERRORE: installazione automatica di Python non riuscita.
echo Installa Python manualmente da https://www.python.org/downloads/
goto failure

:python_restart_needed
echo.
echo Python risulta installato, ma Windows non lo vede ancora.
echo Chiudi questa finestra e fai nuovamente doppio clic sul file BAT.
goto failure

:venv_failed
echo.
echo ERRORE: non sono riuscito a creare l'ambiente .venv.
goto failure

:dependencies_failed
echo.
echo ERRORE: installazione delle dipendenze non riuscita.
echo Controlla la connessione Internet, antivirus e firewall.
goto failure

:app_failed
echo.
echo Deep Dog si e chiuso a causa di un errore.
goto failure

:failure
echo.
pause
exit /b 1

:end
endlocal
