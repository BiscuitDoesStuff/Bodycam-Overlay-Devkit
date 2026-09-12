@echo off
setlocal
REM Packages src\overlay_app.py into a standalone exe with PyInstaller, using
REM BodycamOverlayDevkit.spec as the single source of truth for what gets bundled
REM (icon, data files, hidden imports, --onefile/--windowed) -- edit the spec
REM file directly, not this script, to change any of that. Run from the repo
REM root -- paths below are relative to it.
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

echo Installing/updating dependencies from requirements.txt...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo pip install failed -- see the error above.
    goto :fail
)

echo.
echo Running PyInstaller...
python -m PyInstaller --noconfirm BodycamOverlayDevkit.spec
if errorlevel 1 (
    echo.
    echo PyInstaller failed -- see the error above.
    goto :fail
)

echo.
echo Done. Exe is at dist\BodycamOverlayDevkit.exe
pause
exit /b 0

:fail
echo.
echo Build failed -- see the error above.
pause
exit /b 1
