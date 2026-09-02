@echo off
title captureME - macOS Virtual Machine Launcher
echo ===================================================
echo       captureME macOS Virtual Machine Launcher
echo ===================================================
echo.
echo Launching macOS Docker-OSX container environment...

where docker >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] Docker Desktop is required for macOS Virtual Machine container execution.
    echo     Please ensure Docker Desktop for Windows is installed and running.
    echo.
    echo Alternatively, you can run QEMU directly or test captureME directly on any Mac using:
    echo     bash run_mac.sh
    pause
    exit /b 1
)

echo [*] Docker detected! Starting macOS Virtual Machine container...
docker run -it ^
    --name docker-osx-captureme ^
    -e RAM=4 ^
    -e SMP=4 ^
    -e CORES=4 ^
    -p 50922:22 ^
    -p 5900:5900 ^
    sickcodes/docker-osx:auto

pause
