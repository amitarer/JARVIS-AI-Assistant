@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Impossibile avviare JARVIS: manca .venv\Scripts\pythonw.exe.
    echo Ripristina l'ambiente Python 3.12 nella cartella del progetto.
    pause
    exit /b 2
)
if not exist "%~dp0scripts\start_background.py" (
    echo Impossibile avviare JARVIS: manca scripts\start_background.py.
    pause
    exit /b 2
)
start "" /d "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\start_background.py" %*
exit /b %errorlevel%
