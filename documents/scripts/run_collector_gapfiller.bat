@echo off
title [GAP-FILLER] Accelerated Backfill
color 0D

echo.
echo =====================================================
echo   [GAP-FILLER] Accelerated Backfill Collector
echo   Client ID: 19 ^| Color: PURPLE
echo =====================================================
echo.
echo   PURPOSE: Speed up the most behind timeframes
echo   by splitting Collector 2's overloaded queue.
echo.
echo   Collector 2 has 33K+ requests across 3 timeframes.
echo   This collector takes 30 mins + 1 hour off its plate,
echo   letting Collector 2 focus on 15 mins (17K backlog).
echo.
echo   Also mops up the 1 min + 1 week stragglers (~29 left)
echo   and any remaining 1 day requests.
echo.
echo   NOTE: Run this AFTER Collector 1 finishes daily/weekly.
echo   Close Collector 1 first to free up IB bandwidth.
echo.
echo   Target queue:
echo     30 mins:  ~5,247 pending  (33.7%% done)
echo     1 hour:   ~10,617 pending (56.4%% done)
echo     1 day:    ~828 pending    (96.6%% done)
echo     1 week:   ~14 pending     (99.4%% done)
echo     1 min:    ~15 pending     (99.5%% done)
echo.
echo   Expected: Cuts overall completion time nearly in half.
echo.
echo =====================================================
echo.
echo Press any key to start collection...
pause >nul
echo.

cd /d "%~dp0"
python ib_data_pusher.py --cloud-url http://localhost:8001 --mode collection --client-id 19 --bar-sizes "30 mins,1 hour,1 day,1 week,1 min"

echo.
echo =====================================================
echo   GAP-FILLER COLLECTION COMPLETE
echo =====================================================
echo.
echo All targeted timeframes have been processed.
echo You can close this window.
echo.
pause
