@echo off
title [COLLECTOR-1] 15-Min Backfill
color 06
echo.
echo =====================================================
echo   [COLLECTOR-1] 15-Minute Data (Largest Backlog)
echo   Client ID: 16 ^| Color: DARK YELLOW
echo   Bar sizes: 15 mins
echo =====================================================
echo.

:: Wait for backend before starting collector
echo Waiting for backend to be ready...
:wait_backend_1
curl -s -f -m 3 http://localhost:8001/api/health >nul 2>&1
if %errorlevel%==0 (
    echo Backend is ready - starting collector!
    goto start_collector_1
)
timeout /t 5 /nobreak >nul
goto wait_backend_1

:start_collector_1
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 16 --bar-sizes "15 mins"
pause
