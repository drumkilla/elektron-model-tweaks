@echo off
rem Interactive build. Python 3 is the only requirement.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 tweak.py %* & goto :end)
where python >nul 2>nul && (python tweak.py %* & goto :end)
echo Python 3 not found. Get it from https://www.python.org/downloads/
echo Tick "Add Python to PATH" during setup.
:end
pause
