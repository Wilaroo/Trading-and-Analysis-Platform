@echo off
title TradeCommand Weekend Auto
color 0E

echo ============================================
echo    TradeCommand WEEKEND AUTO MODE
echo    Fully Automated Batch Processing
echo ============================================
echo.
echo This script:
echo   1. Runs StartTrading.bat (starts everything)
echo   2. Waits for services to be ready
echo   3. Auto-triggers batch jobs based on time/day
echo.
echo Press Ctrl+C to cancel, or wait 10 seconds...
timeout /t 10
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
set SCRIPT_DIR=%~dp0
set CLOUD_URL=https://neural-trader-test.preview.emergentagent.com

:: =====================================================
:: STEP 1: RUN STARTTRADING.BAT (but don't wait for health loop)
:: =====================================================
echo [1/3] Starting TradeCommand platform...

:: Run StartTrading.bat in a new window
:: We use 'start /wait' but StartTrading.bat enters a health loop,
:: so we'll just give it time to fully start
start "TradeCommand Startup" cmd /c "%SCRIPT_DIR%StartTrading.bat"

:: Wait for services to start (adjust based on your system)
echo       Waiting 90 seconds for all services to start...
timeout /t 90 /nobreak

:: =====================================================
:: STEP 2: VERIFY SERVICES ARE RUNNING
:: =====================================================
echo.
echo [2/3] Verifying services...

:: Check if IB Gateway port is listening
netstat -an | findstr ":4002 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Gateway: READY
) else (
    echo       IB Gateway: NOT READY - may need manual intervention
)

:: Check cloud health
curl -s -f -m 5 "%CLOUD_URL%/api/health" >nul 2>&1
if %errorlevel%==0 (
    echo       Cloud Backend: READY
) else (
    echo       Cloud Backend: NOT RESPONDING
)

:: Check IB Data Pusher
curl -s -f -m 5 "%CLOUD_URL%/api/ib/pushed-data" | findstr /C:"connected" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Data Pusher: CONNECTED
) else (
    echo       IB Data Pusher: CONNECTING...
)

echo.

:: =====================================================
:: STEP 3: RUN WEEKEND BATCH AUTOMATION
:: =====================================================
echo [3/3] Starting Weekend Batch Automation...
echo.

if exist "%SCRIPT_DIR%weekend_batch.py" (
    python "%SCRIPT_DIR%weekend_batch.py" --cloud-url %CLOUD_URL% --mode auto
    
    if %errorlevel%==0 (
        echo.
        echo ============================================
        echo    WEEKEND AUTO COMPLETE!
        echo ============================================
    ) else (
        echo.
        echo ============================================
        echo    WEEKEND AUTO FINISHED WITH ERRORS
        echo    Check weekend_batch.log for details
        echo ============================================
    )
) else (
    echo [ERROR] weekend_batch.py not found at %SCRIPT_DIR%
    echo Please download from GitHub or cloud
)

echo.
echo Press any key to exit...
pause >nul
