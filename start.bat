@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m app.main %*
) else if exist ".deps\PySide6" (
    set "PYTHONPATH=%~dp0.deps"
    python -m app.main %*
) else (
    python -m app.main %*
)
exit /b %errorlevel%

