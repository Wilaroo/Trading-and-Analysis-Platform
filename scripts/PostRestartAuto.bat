@echo off
title TradeCommand Post-Restart Auto
color 0E

echo ============================================
echo    TradeCommand POST-RESTART AUTO MODE
echo    Resume Data Collection After IB Restart
echo ============================================
echo.
echo IB Gateway restarts daily around 2:00 AM ET.
echo This script runs at 2:15 AM to:
echo   1. Start IB Gateway + Data Pusher
echo   2. Resume any pending data collection
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
set SCRIPT_DIR=%~dp0
set CLOUD_URL=https://xgboost-gpu-trade.preview.emergentagent.com
set LOG_FILE=%SCRIPT_DIR%post_restart.log

:: Log start time
echo ============================================ >> "%LOG_FILE%"
echo Post-Restart Auto Started: %date% %time% >> "%LOG_FILE%"
echo ============================================ >> "%LOG_FILE%"

:: =====================================================
:: STEP 1: CHECK IF THERE'S PENDING WORK
:: =====================================================
echo [1/4] Checking for pending collection work...
echo [1/4] Checking for pending work... >> "%LOG_FILE%"

:: Check the queue
curl -s -f -m 10 "%CLOUD_URL%/api/ib-collector/queue-progress-detailed" > "%TEMP%\queue_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"pending\":" "%TEMP%\queue_check.tmp" > "%TEMP%\pending.tmp"
    type "%TEMP%\pending.tmp"
    
    :: Extract pending count using PowerShell
    for /f %%a in ('powershell -command "(Get-Content '%TEMP%\queue_check.tmp' | ConvertFrom-Json).overall.pending"') do set PENDING_COUNT=%%a
    
    echo       Pending items: %PENDING_COUNT%
    echo       Pending items: %PENDING_COUNT% >> "%LOG_FILE%"
    
    if "%PENDING_COUNT%"=="0" (
        echo       No pending work - exiting.
        echo       No pending work - exiting. >> "%LOG_FILE%"
        del "%TEMP%\queue_check.tmp" 2>nul
        del "%TEMP%\pending.tmp" 2>nul
        goto done_no_work
    )
) else (
    echo       Could not check queue - will try anyway
    echo       Could not check queue - will try anyway >> "%LOG_FILE%"
)
del "%TEMP%\queue_check.tmp" 2>nul
del "%TEMP%\pending.tmp" 2>nul
echo.

:: =====================================================
:: STEP 2: RUN STARTTRADING.BAT (minimal startup)
:: =====================================================
echo [2/4] Starting IB Gateway and Data Pusher...
echo [2/4] Starting IB Gateway and Data Pusher... >> "%LOG_FILE%"

:: Run StartTrading.bat (it will start IB Gateway + Data Pusher)
start "TradeCommand Startup" cmd /c "%SCRIPT_DIR%StartTrading.bat"

:: Wait for services to start (shorter than nightly - just need IB connection)
echo       Waiting 120 seconds for IB Gateway to connect...
timeout /t 120 /nobreak
echo.

:: =====================================================
:: STEP 3: VERIFY IB CONNECTION
:: =====================================================
echo [3/4] Verifying IB connection...
echo [3/4] Verifying IB connection... >> "%LOG_FILE%"

set MAX_ATTEMPTS=10
set ATTEMPT=0

:check_ib_loop
set /a ATTEMPT+=1
if %ATTEMPT% GTR %MAX_ATTEMPTS% (
    echo       IB connection failed after %MAX_ATTEMPTS% attempts
    echo       IB connection failed after %MAX_ATTEMPTS% attempts >> "%LOG_FILE%"
    goto done_failed
)

curl -s -f -m 5 "%CLOUD_URL%/api/ib/status" > "%TEMP%\ib_status.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"connected\":true" "%TEMP%\ib_status.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       IB Gateway: CONNECTED
        echo       IB Gateway: CONNECTED >> "%LOG_FILE%"
        del "%TEMP%\ib_status.tmp" 2>nul
        goto ib_connected
    )
)
del "%TEMP%\ib_status.tmp" 2>nul

echo       Waiting for IB connection... (attempt %ATTEMPT%/%MAX_ATTEMPTS%)
timeout /t 15 /nobreak >nul
goto check_ib_loop

:ib_connected
echo.

:: =====================================================
:: STEP 4: RESUME COLLECTION (Incremental only)
:: =====================================================
echo [4/4] Checking for incremental updates needed...
echo [4/4] Checking for incremental updates... >> "%LOG_FILE%"

:: First check if there's pending work in the queue (from fill-gaps)
curl -s -f -m 10 "%CLOUD_URL%/api/ib-collector/queue-progress-detailed" > "%TEMP%\queue_check2.tmp" 2>nul
if %errorlevel%==0 (
    for /f %%a in ('powershell -command "(Get-Content '%TEMP%\queue_check2.tmp' | ConvertFrom-Json).overall.pending"') do set PENDING_NOW=%%a
    
    if not "%PENDING_NOW%"=="0" (
        echo       Found %PENDING_NOW% pending queue items - resuming...
        curl -s -X POST "%CLOUD_URL%/api/ib-collector/resume" > "%TEMP%\resume_result.tmp" 2>nul
        echo       Resume triggered for existing queue
        echo       Resume triggered for %PENDING_NOW% pending items >> "%LOG_FILE%"
        del "%TEMP%\queue_check2.tmp" 2>nul
        del "%TEMP%\resume_result.tmp" 2>nul
        goto done_success
    )
)
del "%TEMP%\queue_check2.tmp" 2>nul

:: No pending queue items - run incremental update for new bars
echo       No pending queue - checking for new data to fetch...
curl -s -X POST "%CLOUD_URL%/api/ib-collector/incremental-update?max_days_lookback=3" > "%TEMP%\incremental_result.tmp" 2>nul
if %errorlevel%==0 (
    echo       Incremental update result:
    type "%TEMP%\incremental_result.tmp"
    type "%TEMP%\incremental_result.tmp" >> "%LOG_FILE%"
    
    :: Check if any updates were needed
    findstr /C:"up to date" "%TEMP%\incremental_result.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo.
        echo       All data is up to date!
    ) else (
        echo.
        echo       Incremental update started
    )
) else (
    echo       Incremental update request failed
    echo       Incremental update request failed >> "%LOG_FILE%"
)
del "%TEMP%\incremental_result.tmp" 2>nul
echo.

:done_success

:: =====================================================
:: DONE
:: =====================================================
echo ============================================
echo    POST-RESTART AUTO COMPLETE!
echo ============================================
echo.
echo Data collection has been resumed.
echo The IB Data Pusher window must stay open
echo for collection to continue.
echo.
echo Post-Restart Auto Complete: %date% %time% >> "%LOG_FILE%"
goto end

:done_no_work
echo ============================================
echo    NO PENDING WORK - EXITING
echo ============================================
echo Post-Restart Auto: No work to do - %date% %time% >> "%LOG_FILE%"
goto end

:done_failed
echo ============================================
echo    POST-RESTART AUTO FAILED
echo ============================================
echo Could not connect to IB Gateway.
echo Check that IB Gateway is configured for auto-login.
echo.
echo Post-Restart Auto FAILED: %date% %time% >> "%LOG_FILE%"

:end
echo.
echo This window will close in 60 seconds...
echo (or press any key to close now)
timeout /t 60
