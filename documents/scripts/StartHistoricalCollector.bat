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

REM === IB Gateway Auto-Login Credentials ===
set IB_USERNAME=Wilaroo
set IB_PASSWORD=Idgt14gt!
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1030

REM === Parse Arguments ===
set MODE=normal
set TIER=all
set SKIP_LOGIN=0
:parse_args
if "%~1"=="" goto done_args
if /i "%~1"=="--fast" set MODE=fast
if /i "%~1"=="--turbo" set MODE=turbo
if /i "%~1"=="--slow" set MODE=slow
if /i "%~1"=="--intraday" set TIER=intraday
if /i "%~1"=="--swing" set TIER=swing
if /i "%~1"=="--investment" set TIER=investment
if /i "%~1"=="--skip-login" set SKIP_LOGIN=1
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

REM === STEP 2: Check/Start IB Gateway ===
echo.
echo ======================================
echo   Step 2/5: IB Gateway Setup
echo ======================================

if "%SKIP_LOGIN%"=="1" (
    echo   --skip-login flag detected, checking if IB Gateway is running...
    tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I "ibgateway.exe" >NUL
    if errorlevel 1 (
        echo   [!] IB Gateway not running - starting with auto-login...
        goto start_ib_gateway
    ) else (
        echo   [OK] IB Gateway already running - skipping login
        goto ib_gateway_ready
    )
)

:start_ib_gateway
echo   Starting IB Gateway...
start "" "%IB_GATEWAY_PATH%\ibgateway.exe"
echo   Waiting 10 seconds for window to load...
timeout /t 10 /nobreak >nul

echo   Auto-login to account...
REM Use PowerShell to send keystrokes for login
powershell -Command "$wshell = New-Object -ComObject wscript.shell; Start-Sleep -Milliseconds 500; $wshell.AppActivate('IB Gateway'); Start-Sleep -Milliseconds 300; $wshell.SendKeys('%{TAB}'); Start-Sleep -Milliseconds 200"
powershell -Command "$wshell = New-Object -ComObject wscript.shell; $wshell.AppActivate('IB Gateway'); Start-Sleep -Milliseconds 200; $wshell.SendKeys('%IB_USERNAME%'); Start-Sleep -Milliseconds 100; $wshell.SendKeys('{TAB}'); Start-Sleep -Milliseconds 100; $wshell.SendKeys('%IB_PASSWORD%'); Start-Sleep -Milliseconds 100; $wshell.SendKeys('{ENTER}')"

echo   Waiting for authentication (10 seconds)...
timeout /t 10 /nobreak >nul

echo   Dismissing any popups...
powershell -Command "$wshell = New-Object -ComObject wscript.shell; $wshell.AppActivate('IB Gateway'); Start-Sleep -Milliseconds 200; $wshell.SendKeys('{ENTER}'); Start-Sleep -Milliseconds 500; $wshell.SendKeys('{ENTER}')"

echo   Waiting for IB Gateway API port 4002...
:wait_for_ib
timeout /t 2 /nobreak >nul
netstat -an | find "4002" | find "LISTENING" >nul
if errorlevel 1 (
    echo|set /p="."
    goto wait_for_ib
)
echo.
echo   [OK] IB Gateway API ready!

:ib_gateway_ready

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
