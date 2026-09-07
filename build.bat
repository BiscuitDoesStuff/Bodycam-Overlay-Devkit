@echo off
setlocal
REM Packages src\overlay_app.py into a standalone exe with PyInstaller.
REM Run this again any time you (or Claude) edit the src\*.py/.json files, to
REM regenerate dist\BodycamOverlay.exe. Run from the repo root -- paths below
REM are relative to it.
REM
REM Everything below runs as `python -m ...` rather than bare `pip`/
REM `pyinstaller` commands -- on some Python installs (notably the Microsoft
REM Store build) pip installs a package's console-script .exe (pyinstaller.exe
REM included) into a user Scripts folder that isn't on PATH, even though the
REM package itself installed fine. Going through `python -m` sidesteps that
REM entirely, since it only ever needs `python` itself on PATH.
REM
REM This window also stays open and reports what happened either way (success
REM or failure) -- if you're double-clicking this file rather than running it
REM from an already-open terminal, a script with no pause at the end closes
REM the instant it's done, success or failure, so there'd be nothing to read.

where python >nul 2>&1
if errorlevel 1 (
    echo Python isn't on PATH -- install Python and make sure "python" works
    echo from a plain Command Prompt, then try again.
    goto :fail
)

python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo Failed to install PyInstaller -- see the error above.
        goto :fail
    )
)

echo Installing/updating app dependencies from requirements.txt...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo pip install failed -- see the error above.
    goto :fail
)

echo.
echo Running PyInstaller...
python -m PyInstaller --noconfirm --onefile --windowed --name BodycamOverlay ^
    --add-data "src/families.json;." ^
    --add-data "src/maps.json;." ^
    --add-data "src/gamemodes.json;." ^
    --add-data "src/app_icon.ico;." ^
    --add-data "src/mod;mod" ^
    --add-data "src/ue4ss_bundle;ue4ss_bundle" ^
    --hidden-import pystray._win32 ^
    --icon "src/app_icon.ico" ^
    src/overlay_app.py
if errorlevel 1 (
    echo.
    echo PyInstaller failed -- see the error above.
    goto :fail
)

echo.
echo Done. Exe is at dist\BodycamOverlay.exe
pause
exit /b 0

:fail
echo.
echo Build failed -- see the error above.
pause
exit /b 1
