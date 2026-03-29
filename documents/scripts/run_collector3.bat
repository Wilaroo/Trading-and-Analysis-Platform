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
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 18 --bar-sizes "1 hour,1 day,1 week,1 min"
pause
