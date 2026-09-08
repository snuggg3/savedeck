@echo off
rem Build SaveDeck: PyInstaller (onedir) -> Inno Setup installer.
rem Requirements: pip install pyinstaller  +  Inno Setup 6 (iscc on PATH)
setlocal
cd /d "%~dp0.."

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo pyinstaller not found - run:  pip install pyinstaller
    exit /b 1
)

pyinstaller --noconfirm --clean --windowed --onedir --name SaveDeck ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module scipy ^
  --exclude-module PyQt5 --exclude-module PySide6 --exclude-module IPython ^
  main.py
if errorlevel 1 exit /b 1

where iscc >nul 2>nul
if errorlevel 1 (
    echo Inno Setup compiler ^(iscc^) not found - install Inno Setup 6
    exit /b 1
)
iscc packaging\SaveDeck.iss
if errorlevel 1 exit /b 1

echo.
echo Done: dist\SaveDeck-Setup-%MYAPPVERSION%.exe
