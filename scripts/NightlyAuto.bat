@echo off
title TradeCommand Nightly Auto
color 0D

echo ============================================
echo    TradeCommand NIGHTLY AUTO MODE
echo    Automated Data Collection
echo ============================================
echo.
echo This script:
echo   1. Runs StartTrading.bat (starts IB Gateway + services)
echo   2. Waits for services to be ready
echo   3. Triggers nightly Smart Collection
echo   4. Exits when complete
echo.
echo Press Ctrl+C to cancel, or wait 5 seconds...
timeout /t 5
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
set SCRIPT_DIR=%~dp0
set CLOUD_URL=https://ai-quant-hardening.preview.emergentagent.com
set LOG_FILE=%SCRIPT_DIR%nightly_auto.log

:: Log start time
echo ============================================ >> "%LOG_FILE%"
echo Nightly Auto Started: %date% %time% >> "%LOG_FILE%"
echo ============================================ >> "%LOG_FILE%"

:: =====================================================
:: STEP 1: RUN STARTTRADING.BAT
:: =====================================================
echo [1/3] Starting TradeCommand platform...
echo [1/3] Starting TradeCommand platform... >> "%LOG_FILE%"

:: Run StartTrading.bat in a new window
start "TradeCommand Startup" cmd /c "%SCRIPT_DIR%StartTrading.bat"

:: Wait for services to start
echo       Waiting 90 seconds for all services to start...
timeout /t 90 /nobreak

:: =====================================================
:: STEP 2: VERIFY SERVICES ARE RUNNING
:: =====================================================
echo.
echo [2/3] Verifying services...
echo [2/3] Verifying services... >> "%LOG_FILE%"

:: Check if IB Gateway port is listening
netstat -an | findstr ":4002 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Gateway: READY
    echo       IB Gateway: READY >> "%LOG_FILE%"
) else (
    echo       IB Gateway: NOT READY - may need manual intervention
    echo       IB Gateway: NOT READY >> "%LOG_FILE%"
)

:: Check cloud health
curl -s -f -m 5 "%CLOUD_URL%/api/health" >nul 2>&1
if %errorlevel%==0 (
    echo       Cloud Backend: READY
    echo       Cloud Backend: READY >> "%LOG_FILE%"
) else (
    echo       Cloud Backend: NOT RESPONDING
    echo       Cloud Backend: NOT RESPONDING >> "%LOG_FILE%"
)

:: Check IB Data Pusher
curl -s -f -m 5 "%CLOUD_URL%/api/ib/pushed-data" | findstr /C:"connected" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Data Pusher: CONNECTED
    echo       IB Data Pusher: CONNECTED >> "%LOG_FILE%"
) else (
    echo       IB Data Pusher: CONNECTING...
    echo       IB Data Pusher: CONNECTING... >> "%LOG_FILE%"
)

echo.

:: =====================================================
:: STEP 3: RUN NIGHTLY BATCH
:: =====================================================
echo [3/3] Starting Nightly Batch...
echo [3/3] Starting Nightly Batch... >> "%LOG_FILE%"
echo.

if exist "%SCRIPT_DIR%weekend_batch.py" (
    python "%SCRIPT_DIR%weekend_batch.py" --cloud-url %CLOUD_URL% --mode nightly
    
    if %errorlevel%==0 (
        echo.
        echo ============================================
        echo    NIGHTLY AUTO COMPLETE!
        echo ============================================
        echo Nightly Auto Complete: %date% %time% >> "%LOG_FILE%"
    ) else (
        echo.
        echo ============================================
        echo    NIGHTLY AUTO FINISHED WITH ERRORS
        echo    Check weekend_batch.log for details
        echo ============================================
        echo Nightly Auto FAILED: %date% %time% >> "%LOG_FILE%"
    )
) else (
    echo [ERROR] weekend_batch.py not found at %SCRIPT_DIR%
    echo [ERROR] weekend_batch.py not found >> "%LOG_FILE%"
)

:: =====================================================
:: STEP 4: CLEANUP (optional - close windows after batch)
:: =====================================================
echo.
echo Batch complete. Closing services in 30 seconds...
echo (Press Ctrl+C to keep running, or close this window)
timeout /t 30

:: Kill the spawned windows
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Ollama AI Proxy*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Ollama Server*" >nul 2>&1

echo Services stopped. Exiting.
echo Services stopped: %date% %time% >> "%LOG_FILE%"
