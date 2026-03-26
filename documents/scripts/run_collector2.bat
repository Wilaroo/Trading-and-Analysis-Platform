@echo off
title [COLLECTOR-2] Hourly/Mins Backfill
color 0C
echo.
echo =====================================================
echo   [COLLECTOR-2] Hourly + 30min + 15min Data
echo   Client ID: 17 ^| Color: LIGHT RED
echo   Bar sizes: 1 hour, 30 mins, 15 mins
echo =====================================================
echo.
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 17 --bar-sizes "1 hour,30 mins,15 mins"
pause
