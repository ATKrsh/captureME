@echo off
title captureME - Android Virtual Environment & Test Runner
echo ===================================================
echo   captureME Android Virtual Test Environment
echo ===================================================
echo.
echo Launching Android Virtual Machine and Mobile Viewport Tester...

where emulator >nul 2>nul
if %errorlevel% equ 0 (
    echo [*] Android SDK Emulator found! Starting AVD...
    emulator -avd Pixel_API_33
    exit /b 0
)

echo [*] Launching Android Web Application Simulator in Mobile Viewport mode...
start "" "e:\workspace\captureME\android\captureME_android.html"

echo.
echo Android app running in mobile viewport tester!
echo You can also install captureME directly on any Android phone by copying captureME.apk or captureME_android.html.
pause
