@echo off
title AoE2 LAN Party - Team Balancer
echo ========================================
echo   AoE2 LAN Party - Team Balancer
echo ========================================
echo.

:: Check for Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

:: Show Python version
python --version

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo.
    echo Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate venv and install dependencies
echo.
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install -q -r requirements-web.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

:: Check that player_ratings.json exists
if not exist "player_ratings.json" (
    echo ERROR: player_ratings.json not found!
    echo This file must be present for the app to work.
    pause
    exit /b 1
)

:: Get local IP for LAN access
echo.
echo ========================================
echo   Starting web server on port 5050...
echo   Local:  http://localhost:5050
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do (
        echo   LAN:    http://%%b:5050
    )
)
echo.
echo   Press Ctrl+C to stop the server.
echo ========================================
echo.

python run_web.py
pause
