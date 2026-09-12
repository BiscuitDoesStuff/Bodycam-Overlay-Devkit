@echo off
REM Launches the overlay from source (no build step). %~dp0 resolves to this
REM file's own folder no matter where the repo is cloned to, so this works
REM for anyone -- not just on the original author's machine.
python "%~dp0src\overlay_app.py"
