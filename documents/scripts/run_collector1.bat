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
cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 16 --bar-sizes "15 mins"
pause
