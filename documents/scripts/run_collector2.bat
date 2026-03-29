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
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 17 --bar-sizes "5 mins,30 mins"
pause
