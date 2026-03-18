@echo off
REM ================================================================
REM   IB Historical Data Collector - Overnight Ready
REM ================================================================
REM   This script:
REM   1. Pulls latest code from GitHub
REM   2. Checks IB Gateway is running
REM   3. Starts the Backend server (for MongoDB connection)
REM   4. Starts the Historical Data Collector
REM ================================================================

title IB Historical Collector
color 0A

REM === CONFIGURATION ===
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set CLOUD_URL=https://tradecommand.trade
set IB_CLIENT_ID=11
set BATCH_SIZE=5

REM === STEP 1: Pull Latest Code ===
echo.
echo ======================================
echo   Step 1/4: Updating Code from GitHub
echo ======================================
cd /d "%REPO_DIR%"
git pull origin main 2>nul
if errorlevel 1 (
    echo   [!] Git pull failed - continuing with existing code
) else (
    echo   [OK] Code updated successfully
)

REM === STEP 2: Check IB Gateway ===
echo.
echo ======================================
echo   Step 2/4: Checking IB Gateway
echo ======================================
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I "ibgateway.exe" >NUL
if errorlevel 1 (
    echo   [!] IB Gateway not running
    echo.
    echo   Please start IB Gateway and login, then press any key...
    pause >nul
) else (
    echo   [OK] IB Gateway is running
)

REM === STEP 3: Start Backend Server ===
echo.
echo ======================================
echo   Step 3/4: Checking Backend Server
echo ======================================
cd /d "%REPO_DIR%\backend"

curl -s -o nul -w "" http://localhost:8001/api/ib-collector/queue-progress >nul 2>&1
if errorlevel 1 (
    echo   [!] Backend not running - starting it now...
    start "TradeCommand Backend" cmd /k "title TradeCommand Backend && color 0E && cd /d %REPO_DIR%\backend && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
    echo   Waiting 20 seconds for backend to initialize...
    timeout /t 20 /nobreak >nul
    echo   [OK] Backend started
) else (
    echo   [OK] Backend already running
)

REM === STEP 4: Start Historical Collector ===
echo.
echo ======================================
echo   Step 4/4: Starting Data Collector
echo ======================================
echo.
echo   Cloud URL:  %CLOUD_URL%
echo   Client ID:  %IB_CLIENT_ID%
echo   Batch Size: %BATCH_SIZE%
echo.
echo   Press Ctrl+C to stop collection
echo ======================================
echo.

cd /d "%REPO_DIR%\documents\scripts"
python ib_historical_collector.py --cloud-url %CLOUD_URL% --client-id %IB_CLIENT_ID% --batch-size %BATCH_SIZE%

echo.
echo ======================================
echo   Collector Stopped
echo ======================================
pause
