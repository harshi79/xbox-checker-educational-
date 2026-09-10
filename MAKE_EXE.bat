@echo off
title Yorichii Checker - ONE CLICK EXE MAKER - SAME FOLDER
color 0A
echo.
echo __   __           _      _     _  _  ____       _               
echo \ \ / /__  _ __  (_) ___^| |__ (_)(_)/ ___^|  ___^| |__   ___  ___ 
echo  \ V / _ \| '__^| ^| ^|/ __^| '_ \| ^| ^| ^|  _ / __^| '_ \ / _ \/ __^|
echo   ^| ^| (_) ^| ^|    ^| ^| (__^| ^| ^| ^| ^| ^| ^|_^| ^| (__^| ^| ^| ^|  __/ (__ 
echo   ^|_^|\___/^|_^|    ^|_^|\___^|_^| ^|_^|_^|_^|\____^|\___^|_^| ^|_^|\___^|\___^|
echo.
echo   ONE CLICK EXE MAKER - SAME FOLDER OUTPUT
echo   TG: https://t.me/whoevenyori ^| Green ^& Gold Edition
echo.

echo [*] This will make YorichiiChecker.exe in THIS SAME FOLDER
echo [*] Keep these in same folder:
echo     - yorichii_checker_cli.py
echo     - api folder
echo     - yorichii_icon.ico (optional)
echo     - MAKE_EXE.bat (this file)
echo.

echo [*] Checking Python...
python --version
if %errorlevel% neq 0 (
    echo [!] Python not found! Install from python.org and tick "Add to PATH"
    pause
    exit /b 1
)

echo [*] Installing PyInstaller...
python -m pip install pyinstaller pillow --quiet

echo [*] Cleaning old exe...
if exist YorichiiChecker.exe del YorichiiChecker.exe
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist *.spec del /q *.spec

echo [*] Building EXE in SAME FOLDER (may take 1-2 mins)...
python -m PyInstaller --onefile --console --name YorichiiChecker --distpath . --workpath build --specpath . --icon yorichii_icon.ico --add-data "api;api" yorichii_checker_cli.py

if not exist YorichiiChecker.exe (
    echo [!] First try failed, trying without icon...
    python -m PyInstaller --onefile --console --name YorichiiChecker --distpath . --workpath build --specpath . --add-data "api;api" yorichii_checker_cli.py
)

echo [*] Cleaning...
if exist build rmdir /s /q build
if exist *.spec del /q *.spec
if exist dist rmdir /s /q dist

if exist YorichiiChecker.exe (
    echo.
    echo [✓] SUCCESS! YorichiiChecker.exe is in SAME FOLDER!
    for %%A in (YorichiiChecker.exe) do echo     Size: %%~zA bytes
    echo     Branding: Green ^& Gold ^| TG https://t.me/whoevenyori
    echo.
    echo [*] Test it:
    echo     YorichiiChecker.exe --version
    echo     YorichiiChecker.exe -i combos.txt -p proxies.txt -t 20
    echo.
    echo     EXE is ready to share! Same folder!
    echo.
) else (
    echo [!] FAILED! Check errors above
)

pause
