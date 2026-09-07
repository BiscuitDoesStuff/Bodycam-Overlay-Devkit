@echo off
REM Packages src\overlay_app.py into a standalone exe with PyInstaller.
REM Run this again any time you (or Claude) edit the src\*.py/.json files, to
REM regenerate dist\BodycamOverlay.exe. Run from the repo root -- paths below
REM are relative to it.

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

pyinstaller --noconfirm --onefile --windowed --name BodycamOverlay ^
    --add-data "src/families.json;." ^
    --add-data "src/maps.json;." ^
    --add-data "src/gamemodes.json;." ^
    --add-data "src/app_icon.ico;." ^
    --add-data "src/mod;mod" ^
    --add-data "src/ue4ss_bundle;ue4ss_bundle" ^
    --hidden-import pystray._win32 ^
    --icon "src/app_icon.ico" ^
    src/overlay_app.py

echo.
echo Done. Exe is at dist\BodycamOverlay.exe
