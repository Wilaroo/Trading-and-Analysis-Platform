@echo off
echo ==============================
echo   IB Historical Data Collector
echo   Cloud: https://data-sync-issue-3.preview.emergentagent.com
echo ==============================

REM Run with different client_id (11) so it doesn't conflict with trading pusher
python ib_historical_collector.py --cloud-url https://data-sync-issue-3.preview.emergentagent.com --client-id 11 --batch-size 5

pause
