@echo off
REM AnimaDex -- import the public catalogue from animadex.net (wizard).
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist .venv (
    echo No .venv found -- run install.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat

echo.
echo ============================================================
echo   AnimaDex  -  import the public catalogue from animadex.net
echo ============================================================
echo.
echo   1^) Sign in at https://animadex.net
echo   2^) Open  Account  -^>  "Offline dataset export"
echo   3^) Click Generate token, then paste it below.
echo.

set "TOKEN="
set /p "TOKEN=Paste your export token: "
if "!TOKEN!"=="" (
    echo No token entered. Aborting.
    exit /b 1
)

REM Detect a previous import (state file lives in the data dir).
for /f "delims=" %%d in ('python -c "from animadex.config import load; print(load().paths.data_dir)"') do set "DATA_DIR=%%d"
echo.
if exist "!DATA_DIR!\.animadex_import_state.json" (
    echo An earlier import was found -- this run fetches only what changed
    echo since then ^(a fast delta update^).
) else (
    echo No earlier import found -- this will be a full first import.
)

echo.
echo Full-resolution images are MUCH larger ^(tens of GB^) than thumbnails.
echo Thumbnails alone are enough for a fully browsable gallery.
set "IMG="
set "ANS=n"
set /p "ANS=Also download full-resolution images? (y/N): "
if /I "!ANS!"=="y" set "IMG=--with-images"

echo.
echo Starting import...
python scripts\import_from_site.py --token "!TOKEN!" !IMG!
set "RC=!errorlevel!"

echo.
if "!RC!"=="0" (
    echo Import finished. Start the gallery with:  run.bat
) else (
    echo Import failed ^(exit !RC!^). See the messages above.
)
exit /b !RC!
