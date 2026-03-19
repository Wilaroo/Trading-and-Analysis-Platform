@echo off
REM ================================================================
REM   IB Historical Data Collector v3.0 - Complete Edition
REM ================================================================
REM   Auto-starts IB Gateway, logs in, starts backend, and collects data
REM
REM   Usage:
REM     StartHistoricalCollector.bat              (normal speed)
REM     StartHistoricalCollector.bat --fast       (faster collection)
REM     StartHistoricalCollector.bat --skip-login (skip IB Gateway start)
REM ================================================================

title IB Historical Collector v3.0
color 0A

REM === CONFIGURATION ===
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set LOCAL_URL=http://localhost:8001
set IB_CLIENT_ID=99
set BATCH_SIZE=5

REM === IB Gateway Auto-Login ===
set IB_USERNAME=paperesw100000
set IB_PASSWORD=Socr1025!@!?
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_PORT=4002

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
if /i "%~1"=="--skip-login" set SKIP_LOGIN=1
shift
goto parse_args
:done_args

echo.
echo ================================================================
echo   IB Historical Data Collector v3.0
echo ================================================================
echo   Mode: %MODE%
echo   Client ID: %IB_CLIENT_ID%
echo ================================================================
echo.

REM === STEP 1: Pull Latest Code ===
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

REM === STEP 2: IB Gateway ===
echo.
echo ======================================
echo   Step 2/5: IB Gateway Setup
echo ======================================

if "%SKIP_LOGIN%"=="1" (
    echo   --skip-login: Checking if IB Gateway running...
    tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I "ibgateway.exe" >NUL
    if not errorlevel 1 (
        echo   [OK] IB Gateway already running
        goto ib_ready
    )
    echo   [!] Not running - will start and login...
)

REM Check if already running and listening
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo   [OK] IB Gateway already logged in and ready!
    goto ib_ready
)

echo   Starting IB Gateway...
start "" "%IB_GATEWAY_PATH%"
echo   Waiting 5 seconds for window to load...
timeout /t 5 /nobreak >nul

echo   Entering credentials...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 1000
    echo WshShell.AppActivate "IB Gateway"
    echo WScript.Sleep 500
    echo WshShell.SendKeys "%IB_USERNAME%"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{TAB}"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "%IB_PASSWORD%"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul

echo   Waiting 10 seconds for authentication...
timeout /t 10 /nobreak >nul

echo   Closing popups...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 500
    echo WshShell.AppActivate "IB Gateway"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{ENTER}"
    echo WScript.Sleep 1000
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_popup.vbs"
cscript //nologo "%TEMP%\ib_popup.vbs"
del "%TEMP%\ib_popup.vbs" 2>nul

echo   Waiting for API port %IB_PORT%...
:wait_ib
timeout /t 2 /nobreak >nul
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo|set /p="."
    goto wait_ib
)
echo.
echo   [OK] IB Gateway ready!

:ib_ready

REM === STEP 3: Backend Server ===
echo.
echo ======================================
echo   Step 3/5: Backend Server
echo ======================================
cd /d "%REPO_DIR%\backend"

curl.exe -s -o nul -w "" %LOCAL_URL%/api/health >nul 2>&1
if errorlevel 1 (
    echo   [!] Starting backend...
    if exist "%REPO_DIR%\backend\venv\Scripts\python.exe" (
        start "TradeCommand Backend" cmd /k "title TradeCommand Backend && color 0E && cd /d %REPO_DIR%\backend && %REPO_DIR%\backend\venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8001"
    ) else (
        start "TradeCommand Backend" cmd /k "title TradeCommand Backend && color 0E && cd /d %REPO_DIR%\backend && python -m uvicorn server:app --host 0.0.0.0 --port 8001"
    )
    echo   Waiting for backend...
    :wait_backend
    timeout /t 1 /nobreak >nul
    curl.exe -s -o nul -w "" %LOCAL_URL%/api/health >nul 2>&1
    if errorlevel 1 (
        echo|set /p="."
        goto wait_backend
    )
    echo.
    echo   [OK] Backend started
) else (
    echo   [OK] Backend already running
)

REM === STEP 4: Queue Missing Data ===
echo.
echo ======================================
echo   Step 4/5: Queuing Missing Data
echo ======================================
echo.
echo   ADV Cache Stats:
curl.exe -s %LOCAL_URL%/api/ib-collector/adv-cache-stats
echo.
echo.
echo   Calling fill-gaps to queue missing data...
curl.exe -s -X POST "%LOCAL_URL%/api/ib-collector/fill-gaps"
echo.
echo.
echo   Queue Status:
curl.exe -s %LOCAL_URL%/api/ib-collector/queue-progress
echo.
timeout /t 3 /nobreak >nul

REM === STEP 5: Start Collector ===
echo.
echo ======================================
echo   Step 5/5: Starting Collector
echo ======================================
echo   Client ID: %IB_CLIENT_ID%
echo   Mode: %MODE%
echo   Press Ctrl+C to stop
echo ======================================
echo.

cd /d "%REPO_DIR%\documents\scripts"

if "%MODE%"=="fast" (
    echo   *** FAST MODE ***
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size 8 --fast
) else if "%MODE%"=="turbo" (
    echo   *** TURBO MODE ***
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size 10 --turbo
) else if "%MODE%"=="slow" (
    echo   *** SLOW MODE ***
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size 2 --slow
) else (
    echo   *** NORMAL MODE ***
    python ib_historical_collector.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --batch-size %BATCH_SIZE%
)

echo.
echo ======================================
echo   Collector Stopped
echo ======================================
pause
