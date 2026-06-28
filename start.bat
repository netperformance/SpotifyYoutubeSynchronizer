@echo off
cd /d "%~dp0"

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo Virtuelle Umgebung nicht gefunden. Bitte zuerst 'python -m venv .venv' ausfuehren.
    pause
    exit /b 1
)

python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
