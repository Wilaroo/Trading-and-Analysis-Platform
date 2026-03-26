@echo off
title [COLLECTOR-3] 5-Min Backfill
color 03
echo.
echo =====================================================
echo   [COLLECTOR-3] 5-Minute Data
echo   Client ID: 18 ^| Color: AQUA
echo   Bar sizes: 5 mins (3M duration per request)
echo =====================================================
echo.
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 18 --bar-sizes "5 mins"
pause
