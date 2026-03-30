@echo off
title [COLLECTOR-3] Hourly + Daily + Remaining
color 03
echo.
echo =====================================================
echo   [COLLECTOR-3] Hourly + Daily + Weekly + 1-Min
echo   Client ID: 18 ^| Color: AQUA
echo   Bar sizes: 1 hour, 1 day, 1 week, 1 min
echo =====================================================
echo.

:: Wait for backend before starting collector
echo Waiting for backend to be ready...
:wait_backend_3
curl -s -f -m 3 http://localhost:8001/api/health >nul 2>&1
if %errorlevel%==0 (
    echo Backend is ready - starting collector!
    goto start_collector_3
)
timeout /t 5 /nobreak >nul
goto wait_backend_3

:start_collector_3
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 18 --bar-sizes "1 hour,1 day,1 week,1 min"
pause
