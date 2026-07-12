@echo off
REM AnimaDex launcher (Windows) — Hikari setup
cd /d "%~dp0"
if not exist .venv (
    echo [!] No se encontro .venv. Ejecuta primero el install (py -3.11 -m venv .venv; ...)
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:5000
python -m animadex serve
