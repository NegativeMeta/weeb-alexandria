@echo off
REM Weeb Alexandria unified MCP server (stdio)
setlocal
set "PYTHONPATH="
set "TAGLIB_DB=%~dp0tag_library.db"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [!] No se encontro .venv en WeebAlexandria.
    exit /b 1
)
".venv\Scripts\python.exe" -m weeb_alexandria_mcp.server
endlocal
