@echo off
setlocal
cd /d "%~dp0"
set "SMARTREPORT_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "SMARTREPORT_PYTHON=.venv\Scripts\python.exe"
if not exist ".venv\Scripts\python.exe" if exist ".deps\PySide6" set "PYTHONPATH=%~dp0.deps"
"%SMARTREPORT_PYTHON%" -m PyInstaller --noconfirm --windowed --onedir --name SmartReport ^
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 ^
    --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module scipy ^
    --exclude-module IPython --exclude-module numba --exclude-module PIL --exclude-module lxml ^
    --exclude-module tkinter --exclude-module pymupdf_layout ^
    --distpath ".smartreport\dist" --workpath ".smartreport\build" --specpath ".smartreport" launcher.py
exit /b %errorlevel%

