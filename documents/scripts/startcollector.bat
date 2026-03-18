@echo off
REM ================================================================
REM   IB Historical Data Collector - Overnight Ready
REM ================================================================
REM   This script:
REM   1. Pulls latest code from GitHub
REM   2. Starts IB Gateway (if not running)
REM   3. Starts the Backend server (for MongoDB connection)
REM   4. Starts the Historical Data Collector
REM ================================================================

title IB Historical Collector Setup
color 0A

REM === CONFIGURATION ===
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set CLOUD_URL=https://tradecommand.trade
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1030
set IB_CLIENT_ID=11
set BATCH_SIZE=5

REM === STEP 1: Pull Latest Code ===
echo.
echo ==============================
echo   Step 1: Updating Code
echo ==============================
cd /d "%REPO_DIR%"
echo Pulling latest from GitHub...
git pull origin main 2>nul
if errorlevel 1 (
    echo Warning: Git pull failed - continuing with existing code
) else (
    echo Code updated successfully!
)

REM === STEP 2: Check IB Gateway ===
echo.
echo ==============================
echo   Step 2: IB Gateway Check
echo ==============================
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I "ibgateway.exe" >NUL
if errorlevel 1 (
    echo IB Gateway not running - please start it manually and login
    echo.
    echo After IB Gateway is running, press any key to continue...
    pause >nul
) else (
    echo IB Gateway is already running!
)

REM === STEP 3: Start Backend Server ===
echo.
echo ==============================
echo   Step 3: Starting Backend
echo ==============================
cd /d "%REPO_DIR%\backend"

REM Check if backend is already running
curl -s http://localhost:8001/api/health >nul 2>&1
if errorlevel 1 (
    echo Starting backend server...
    start "TradeCommand Backend" cmd /k "title Backend Server && color 0E && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
    echo Waiting for backend to start...
    timeout /t 15 /nobreak >nul
    
    REM Verify backend started
    curl -s http://localhost:8001/api/health >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Backend failed to start!
        echo Check the Backend Server window for errors.
        pause
        exit /b 1
    )
    echo Backend started successfully!
) else (
    echo Backend is already running!
)

REM === STEP 4: Start Historical Collector ===
echo.
echo ==============================
echo   Step 4: Starting Collector
echo ==============================
echo.
echo   Cloud URL: %CLOUD_URL%
echo   Client ID: %IB_CLIENT_ID%
echo   Batch Size: %BATCH_SIZE%
echo.
echo ==============================
echo.

cd /d "%REPO_DIR%\documents\scripts"

REM Start the collector
echo Starting historical data collector...
echo.
python ib_historical_collector.py --cloud-url %CLOUD_URL% --client-id %IB_CLIENT_ID% --batch-size %BATCH_SIZE%

REM If we get here, collector stopped
echo.
echo ==============================
echo   Collector Stopped
echo ==============================
echo.
pause
