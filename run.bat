@echo off
cd /d "%~dp0"

echo Starting AetherWaves Web Server...

:: Load .env file if present
if exist ".env" (
    for /f "usebackq tokens=*" %%i in (".env") do (
        set "%%i"
    )
)

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) else if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo [ERROR] Virtual environment not found in "venv" or ".venv".
    pause
    exit /b 1
)

set PYTHONPATH=src
start "" http://127.0.0.1:8000
python -m aetherwaves.server
pause
