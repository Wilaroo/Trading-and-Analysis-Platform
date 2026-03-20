@echo off
REM ================================================================
REM   IB Historical Collector v3.0 - OPTIMIZED TEST VERSION
REM ================================================================
REM   Tests the new optimized collector with lifted pacing limits
REM
REM   Usage:
REM     StartCollectorV3.bat                    (optimized - default)
REM     StartCollectorV3.bat --turbo            (maximum speed)
REM     StartCollectorV3.bat --conservative     (safer, slower)
REM ================================================================

title IB Historical Collector v3.0 - OPTIMIZED
color 0B

REM === CONFIGURATION ===
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set LOCAL_URL=http://localhost:8001
set IB_CLIENT_ID=99

REM === Parse Arguments ===
set MODE=optimized
:parse_args
if "%~1"=="" goto done_args
if /i "%~1"=="--turbo" set MODE=turbo
if /i "%~1"=="--conservative" set MODE=conservative
shift
goto parse_args
:done_args

echo.
echo ================================================================
echo   IB Historical Data Collector v3.0 - OPTIMIZED
echo ================================================================
echo   Key Changes from v2:
echo   - Removed 55/10min internal pacing (lifted for 1min+ bars)
echo   - Default batch size: 12 (was 3-6)
echo   - Default delay: 0.3s (was 1.0s)
echo   - Only burst limit enforced (6 req/2sec per symbol)
echo ================================================================
echo   Mode: %MODE%
echo   Client ID: %IB_CLIENT_ID%
echo ================================================================
echo.

REM === Check if backend is running ===
echo Checking backend status...
curl.exe -s -o nul -w "%%{http_code}" %LOCAL_URL%/api/health > temp_status.txt
set /p STATUS=<temp_status.txt
del temp_status.txt

if not "%STATUS%"=="200" (
    echo.
    echo [ERROR] Backend is not running at %LOCAL_URL%
    echo Please start the backend first with TradeCommand_Ultimate.bat
    echo.
    pause
    exit /b 1
)

echo Backend is running!
echo.

REM === Check IB Gateway connection ===
echo Checking IB Gateway connection...
curl.exe -s %LOCAL_URL%/api/ib/status | findstr /i "connected" >nul
if errorlevel 1 (
    echo.
    echo [WARNING] IB Gateway may not be connected
    echo The collector will attempt to connect on its own
    echo.
)

REM === Show current queue status ===
echo.
echo Current Queue Status:
curl.exe -s %LOCAL_URL%/api/ib-collector/queue-progress
echo.
echo.

REM === Start the V3 collector ===
echo ================================================================
echo   Starting v3.0 Collector
echo   Press Ctrl+C to stop
echo ================================================================
echo.

cd /d "%REPO_DIR%\documents\scripts"

if "%MODE%"=="turbo" (
    echo *** TURBO MODE - Maximum throughput ***
    echo Batch: 18, Delay: 0.2s
    echo.
    python ib_historical_collector_v3.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --turbo
) else if "%MODE%"=="conservative" (
    echo *** CONSERVATIVE MODE - Safer, slower ***
    echo Batch: 6, Delay: 0.5s
    echo.
    python ib_historical_collector_v3.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID% --conservative
) else (
    echo *** OPTIMIZED MODE - Balanced speed ***
    echo Batch: 12, Delay: 0.3s
    echo.
    python ib_historical_collector_v3.py --url %LOCAL_URL% --client-id %IB_CLIENT_ID%
)

echo.
echo ================================================================
echo   Collector Stopped
echo ================================================================
echo.
pause
