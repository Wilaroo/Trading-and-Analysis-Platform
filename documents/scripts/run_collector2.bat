@echo off
title [COLLECTOR-2] 5-Min + 30-Min Backfill
color 0C
echo.
echo =====================================================
echo   [COLLECTOR-2] 5-Minute + 30-Minute Data
echo   Client ID: 17 ^| Color: LIGHT RED
echo   Bar sizes: 5 mins, 30 mins
echo =====================================================
echo.

:: Wait for backend before starting collector
echo Waiting for backend to be ready...
:wait_backend_2
curl -s -f -m 3 http://localhost:8001/api/health >nul 2>&1
if %errorlevel%==0 (
    echo Backend is ready - starting collector!
    goto start_collector_2
)
timeout /t 5 /nobreak >nul
goto wait_backend_2

:start_collector_2
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 17 --bar-sizes "5 mins,30 mins"
pause
