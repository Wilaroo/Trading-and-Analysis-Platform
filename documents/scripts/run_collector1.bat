@echo off
title [COLLECTOR-1] Daily/Weekly Backfill
color 06
echo.
echo =====================================================
echo   [COLLECTOR-1] Daily + Weekly Data
echo   Client ID: 16 ^| Color: DARK YELLOW
echo   Bar sizes: 1 day, 1 week
echo =====================================================
echo.
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 16 --bar-sizes "1 day,1 week"
pause
