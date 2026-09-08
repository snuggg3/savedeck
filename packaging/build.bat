@echo off
rem Build SaveDeck: PyInstaller (onedir) -> Inno Setup installer.
rem Requirements: pip install pyinstaller  +  Inno Setup 6 or 7
rem (the script auto-finds ISCC.exe; PATH is not required)
setlocal
cd /d "%~dp0.."

rem ---- 1. build the app with PyInstaller -----------------------------------
set "PYI=pyinstaller"
where pyinstaller >nul 2>nul || set "PYI=python -m PyInstaller"

%PYI% --noconfirm --clean --windowed --onedir --name SaveDeck ^
  --exclude-module matplotlib --exclude-module numpy --exclude-module scipy ^
  --exclude-module PyQt5 --exclude-module PySide6 --exclude-module IPython ^
  main.py
if errorlevel 1 (
    echo PyInstaller build failed - is pyinstaller installed?
    echo Run:  pip install pyinstaller   ^(or activate your venv first^)
    exit /b 1
)

rem ---- 2. locate the Inno Setup compiler (ISCC.exe) ------------------------
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC call :find_iscc
if not defined ISCC (
    echo Inno Setup compiler ^(ISCC.exe^) not found.
    echo Searched: PATH, Program Files, Program Files ^(x86^) and
    echo %LocalAppData%\Programs - install Inno Setup 6/7, or add its
    echo folder to PATH.
    exit /b 1
)

rem ---- 3. compile the installer ---------------------------------------------
echo Using Inno compiler: %ISCC%
"%ISCC%" packaging\SaveDeck.iss
if errorlevel 1 exit /b 1

echo.
echo Done - installer written to dist\SaveDeck-Setup-1.0.0.exe
exit /b 0

:find_iscc
for %%P in (
    "%LocalAppData%\Programs\Inno Setup 7"
    "%LocalAppData%\Programs\Inno Setup 6"
    "%ProgramFiles%\Inno Setup 7"
    "%ProgramFiles%\Inno Setup 6"
    "%ProgramFiles(x86)%\Inno Setup 7"
    "%ProgramFiles(x86)%\Inno Setup 6"
) do (
    if exist "%%~P\ISCC.exe" (
        set "ISCC=%%~P\ISCC.exe"
        exit /b 0
    )
)
exit /b 1
