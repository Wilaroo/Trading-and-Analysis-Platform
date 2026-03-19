@echo off
REM ================================================================
REM   IB Historical Data Collector - Intraday Gap Filler v2.0
REM ================================================================
REM   This script:
REM   1. Pulls latest code from GitHub
REM   2. Checks/Starts IB Gateway
REM   3. Starts the Backend server (for MongoDB connection)
REM   4. Queues up missing intraday data based on ADV tiers
REM   5. Starts the Historical Data Collector
REM
REM   Usage:
REM     StartHistoricalCollector.bat              (normal speed, all tiers)
REM     StartHistoricalCollector.bat --fast       (faster collection)
REM     StartHistoricalCollector.bat --turbo      (aggressive, may hit limits)
REM     StartHistoricalCollector.bat --intraday   (only 500K+ ADV symbols)
REM     StartHistoricalCollector.bat --fast --intraday
REM ================================================================

title IB Historical Collector v2.0
color 0A

REM === CONFIGURATION ===
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set LOCAL_URL=http://localhost:8001
set IB_CLIENT_ID=99
set BATCH_SIZE=5

REM === Parse Arguments ===
set MODE=normal
set TIER=all
:parse_args
if "%~1"=="" goto done_args
if /i "%~1"=="--fast" set MODE=fast
if /i "%~1"=="--turbo" set MODE=turbo
if /i "%~1"=="--slow" set MODE=slow
if /i "%~1"=="--intraday" set TIER=intraday
if /i "%~1"=="--swing" set TIER=swing
if /i "%~1"=="--investment" set TIER=investment
shift
goto parse_args
:done_args

echo.
echo ================================================================
echo   IB Historical Data Collector v2.0 - Intraday Gap Filler
echo ================================================================
echo   Mode: %MODE%
echo   Tier: %TIER%
echo.
echo   Tiers explained:
echo     intraday   = 500K+ ADV   - gets 1min, 5min, 15min, 1hour, 1day
echo     swing      = 100K-500K   - gets 5min, 30min, 1hour, 1day
echo     investment = 50K-100K    - gets 1hour, 1day, 1week
echo     all        = all tiers
echo ================================================================
echo.

REM === STEP 1: Pull Latest Code ===
echo.
echo ======================================
echo   Step 1/5: Updating Code from GitHub
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
echo   Step 2/5: Checking IB Gateway
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
echo   Step 3/5: Checking Backend Server
echo ======================================
cd /d "%REPO_DIR%\backend"

curl.exe -s -o nul -w "" %LOCAL_URL%/api/health >nul 2>&1
if errorlevel 1 (
    echo   [!] Backend not running - starting it now...
    
    REM Try multiple methods to start the backend
    if exist "%REPO_DIR%\venv\Scripts\python.exe" (
        echo   Using venv Python...
        start "TradeCommand Backend" cmd /k "title TradeCommand Backend && color 0E && cd /d %REPO_DIR%\backend && %REPO_DIR%\venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8001"
    ) else if exist "%REPO_DIR%\backend\venv\Scripts\python.exe" (
        echo   Using backend venv Python...
        start "TradeCommand Backend" cmd /k "title TradeCommand Backend && color 0E && cd /d %REPO_DIR%\backend && %REPO_DIR%\backend\venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8001"
    ) else (
        echo   Using system Python...
        start "TradeCommand Backend" cmd /k "title TradeCommand Backend && color 0E && cd /d %REPO_DIR%\backend && python -m uvicorn server:app --host 0.0.0.0 --port 8001"
    )
    
    echo   Waiting for backend to start...
    set BACKEND_READY=0
    for /L %%i in (1,1,60) do (
        timeout /t 1 /nobreak >nul
        curl.exe -s -o nul -w "" %LOCAL_URL%/api/health >nul 2>&1
        if not errorlevel 1 (
            set BACKEND_READY=1
            goto backend_started
        )
        echo|set /p="."
    )
    :backend_started
    echo.
    if "%BACKEND_READY%"=="1" (
        echo   [OK] Backend started successfully
    ) else (
        echo   [!] Backend may still be starting - continuing anyway
    )
) else (
    echo   [OK] Backend already running
)

REM === STEP 4: Queue Missing Intraday Data ===
echo.
echo ======================================
echo   Step 4/5: Queuing Missing Data
echo ======================================
echo.
echo   Current ADV cache stats:
curl.exe -s %LOCAL_URL%/api/ib-collector/adv-cache-stats 2>nul
echo.
echo.

echo   Queueing missing intraday data for %TIER% tier(s)...
echo   This identifies gaps and adds them to the collection queue.
echo.

REM Call fill-gaps endpoint to queue missing data
if "%TIER%"=="all" (
    echo   Calling: POST %LOCAL_URL%/api/ib-collector/fill-gaps
    curl.exe -s -X POST "%LOCAL_URL%/api/ib-collector/fill-gaps"
) else (
    echo   Calling: POST %LOCAL_URL%/api/ib-collector/fill-gaps?tier_filter=%TIER%
    curl.exe -s -X POST "%LOCAL_URL%/api/ib-collector/fill-gaps?tier_filter=%TIER%"
)
echo.
echo.

REM Show queue status after filling
echo   Queue status after filling gaps:
curl.exe -s %LOCAL_URL%/api/ib-collector/queue-progress
echo.
echo.

echo   Waiting 5 seconds before starting collector...
timeout /t 5 /nobreak >nul

REM === STEP 5: Start Historical Collector ===
echo.
echo ======================================
echo   Step 5/5: Starting Data Collector
echo ======================================
echo.
echo   Backend URL: %LOCAL_URL%
echo   Client ID:   %IB_CLIENT_ID%
echo   Mode:        %MODE%
echo   Tier:        %TIER%
echo.
echo   Press Ctrl+C to stop collection
echo ======================================
echo.

cd /d "%REPO_DIR%\documents\scripts"

REM Start collector with appropriate speed mode
if "%MODE%"=="turbo" (
    echo   Starting in TURBO mode - aggressive collection...
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size 10 --turbo
) else if "%MODE%"=="fast" (
    echo   Starting in FAST mode - optimized throughput...
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size 8 --fast
) else if "%MODE%"=="slow" (
    echo   Starting in SLOW mode - conservative pacing...
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size 2 --slow
) else (
    echo   Starting in NORMAL mode...
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size %BATCH_SIZE%
)

echo.
echo ======================================
echo   Collector Stopped
echo ======================================
pause
