@echo off
REM ================================================================
REM IB Collection Status Monitor
REM ================================================================
REM Opens a new terminal window showing live collection progress
REM 
REM Run this AFTER starting the historical collector
REM ================================================================

title IB Collection Status Monitor

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found! Please install Python 3.
    pause
    exit /b 1
)

REM Get the script directory
set SCRIPT_DIR=%~dp0

REM Check if the status script exists
if not exist "%SCRIPT_DIR%collector_status.py" (
    echo Error: collector_status.py not found in %SCRIPT_DIR%
    pause
    exit /b 1
)

REM Set API base (default to localhost)
set API_BASE=http://localhost:8001

echo.
echo ========================================
echo  IB Collection Status Monitor
echo ========================================
echo  API: %API_BASE%
echo  Press Ctrl+C to exit
echo ========================================
echo.

REM Run the status monitor in watch mode
python "%SCRIPT_DIR%collector_status.py" --watch

pause
