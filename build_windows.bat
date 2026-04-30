@echo off
REM Build stockscanner.exe locally on Windows.
REM Requires: Python 3.10+ on PATH. The resulting .exe is self-contained — drop
REM it anywhere and double-click.

setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not on PATH. Install Python 3.10+ from python.org and rerun.
    exit /b 1
)

echo === Creating virtual environment ===
python -m venv .venv
if errorlevel 1 exit /b 1

echo === Installing dependencies ===
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo === Building stockscanner.exe ===
pyinstaller --clean stockscanner.spec
if errorlevel 1 (
    echo BUILD FAILED.
    exit /b 1
)

echo.
echo === Done ===
echo Output: dist\stockscanner.exe
echo Test it: dist\stockscanner.exe scan --top 10
