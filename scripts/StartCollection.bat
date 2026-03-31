@echo off
title TradeCommand - DATA COLLECTION MODE
color 0E

echo ============================================
echo    TradeCommand DATA COLLECTION MODE
echo         (Historical Data Fetcher)
echo ============================================
echo.
echo   This mode dedicates ALL bandwidth to
echo   historical data collection.
echo.
echo   LIVE TRADING IS PAUSED in this mode.
echo.
echo   Use during off-hours for fastest collection.
echo.
echo ============================================
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
set CLOUD_URL=https://ai-broker-lab.preview.emergentagent.com
set GITHUB_RAW=https://raw.githubusercontent.com/Wilaroo/Trading-and-Analysis-Platform/main/documents
set SCRIPT_DIR=%~dp0
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_PORT=4002

:: =====================================================
:: STEP 1: UPDATE SCRIPTS
:: =====================================================
echo [1/4] Checking for script updates...

:: Try to download latest ib_data_pusher.py from cloud
curl -s -f "%CLOUD_URL%/api/scripts/ib_data_pusher.py" > "%SCRIPT_DIR%ib_data_pusher.py.tmp" 2>nul
if %errorlevel%==0 (
    move /y "%SCRIPT_DIR%ib_data_pusher.py.tmp" "%SCRIPT_DIR%ib_data_pusher.py" >nul
    echo       ib_data_pusher.py: Updated from cloud
) else (
    del "%SCRIPT_DIR%ib_data_pusher.py.tmp" 2>nul
    echo       ib_data_pusher.py: Using local
)
echo.

:: =====================================================
:: STEP 2: CHECK IB GATEWAY
:: =====================================================
echo [2/4] Checking IB Gateway...

:: Check if IB Gateway is running
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo       IB Gateway already running on port %IB_PORT%
) else (
    echo       Starting IB Gateway...
    if exist "%IB_GATEWAY_PATH%" (
        start "" "%IB_GATEWAY_PATH%"
        echo       Waiting for IB Gateway to start (30 seconds)...
        timeout /t 30 /nobreak >nul
    ) else (
        echo       [ERROR] IB Gateway not found at %IB_GATEWAY_PATH%
        echo       Please start IB Gateway manually and press any key...
        pause >nul
    )
)
echo.

:: =====================================================
:: STEP 3: VERIFY IB CONNECTION
:: =====================================================
echo [3/4] Verifying IB Gateway connection...

netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo       IB Gateway API ready on port %IB_PORT%!
) else (
    echo       [WARNING] IB Gateway API not responding
    echo       Please ensure IB Gateway is running and logged in.
    echo       Press any key to continue anyway...
    pause >nul
)
echo.

:: =====================================================
:: STEP 4: START DATA COLLECTION
:: =====================================================
echo [4/4] Starting Data Collection Mode...
echo.
echo ============================================
echo   DATA COLLECTION STARTING
echo ============================================
echo.
echo   - All bandwidth dedicated to historical data
echo   - Live trading is PAUSED
echo   - Orders are DISABLED
echo   - Press Ctrl+C to stop collection
echo.
echo ============================================
echo.

:: Start the data pusher in collection mode
python "%SCRIPT_DIR%ib_data_pusher.py" --cloud-url "%CLOUD_URL%" --mode collection

echo.
echo ============================================
echo   DATA COLLECTION STOPPED
echo ============================================
echo.
echo Press any key to exit...
pause >nul
