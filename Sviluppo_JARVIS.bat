@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" -B "%~dp0development\monitor.py"
