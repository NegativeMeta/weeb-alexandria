@echo off
REM AnimaDex MCP server launcher (stdio) — Hikari setup
REM Importante: limpiamos PYTHONPATH para NO tocar el venv de Hermes.
setlocal
set "PYTHONPATH="
cd /d "%~dp0.."
if not exist .venv (
    echo [!] No se encontro .venv en el repo AnimaDex.
    pause & exit /b 1
)
call .venv\Scripts\activate.bat
set "PYTHONPATH="
python -m animadex_mcp.server
endlocal
