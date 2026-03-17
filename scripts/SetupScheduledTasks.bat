@echo off
title TradeCommand Task Scheduler Setup
color 0B

echo ============================================
echo    TradeCommand Task Scheduler Setup
echo    Automated Weekend + Nightly Batch Jobs
echo ============================================
echo.
echo This script will create Windows Task Scheduler tasks:
echo.
echo   1. TradeCommand_Weekend
echo      - Runs: Saturday at 8:00 AM
echo      - Does: Full data collection + training + simulations
echo.
echo   2. TradeCommand_Nightly  
echo      - Runs: Monday-Friday at 9:00 PM
echo      - Does: Quick Smart Collection refresh
echo.
echo   3. TradeCommand_PostRestart (NEW!)
echo      - Runs: Daily at 2:15 AM (after IB Gateway restart)
echo      - Does: Resume any pending data collection
echo.
echo Press any key to continue or Ctrl+C to cancel...
pause >nul
echo.

:: Get the script directory
set SCRIPT_DIR=%~dp0

:: =====================================================
:: DELETE EXISTING TASKS (if any)
:: =====================================================
echo [1/5] Removing any existing tasks...
schtasks /delete /tn "TradeCommand_Weekend" /f >nul 2>&1
schtasks /delete /tn "TradeCommand_Nightly" /f >nul 2>&1
schtasks /delete /tn "TradeCommand_PostRestart" /f >nul 2>&1
echo       Done.
echo.

:: =====================================================
:: CREATE WEEKEND TASK (Saturdays at 8 AM)
:: =====================================================
echo [2/5] Creating Weekend Task...
echo       Schedule: Every Saturday at 8:00 AM

schtasks /create /tn "TradeCommand_Weekend" ^
    /tr "\"%SCRIPT_DIR%WeekendAuto.bat\"" ^
    /sc weekly /d SAT /st 08:00 ^
    /rl highest ^
    /f

if %errorlevel%==0 (
    echo       Weekend task created successfully!
) else (
    echo       [ERROR] Failed to create weekend task
)
echo.

:: =====================================================
:: CREATE NIGHTLY TASK (Weekdays at 9 PM)
:: =====================================================
echo [3/5] Creating Nightly Task...
echo       Schedule: Monday-Friday at 9:00 PM

schtasks /create /tn "TradeCommand_Nightly" ^
    /tr "\"%SCRIPT_DIR%NightlyAuto.bat\"" ^
    /sc weekly /d MON,TUE,WED,THU,FRI /st 21:00 ^
    /rl highest ^
    /f

if %errorlevel%==0 (
    echo       Nightly task created successfully!
) else (
    echo       [ERROR] Failed to create nightly task
)
echo.

:: =====================================================
:: CREATE POST-RESTART TASK (Daily at 2:15 AM)
:: =====================================================
echo [4/5] Creating Post-Restart Task...
echo       Schedule: Daily at 2:15 AM (after IB Gateway restart)

schtasks /create /tn "TradeCommand_PostRestart" ^
    /tr "\"%SCRIPT_DIR%PostRestartAuto.bat\"" ^
    /sc daily /st 02:15 ^
    /rl highest ^
    /f

if %errorlevel%==0 (
    echo       Post-Restart task created successfully!
) else (
    echo       [ERROR] Failed to create post-restart task
)
echo.

:: =====================================================
:: VERIFY TASKS
:: =====================================================
echo [5/5] Verifying scheduled tasks...
echo.
echo --- TradeCommand_Weekend ---
schtasks /query /tn "TradeCommand_Weekend" /fo list | findstr /C:"Status" /C:"Next Run"
echo.
echo --- TradeCommand_Nightly ---
schtasks /query /tn "TradeCommand_Nightly" /fo list | findstr /C:"Status" /C:"Next Run"
echo.
echo --- TradeCommand_PostRestart ---
schtasks /query /tn "TradeCommand_PostRestart" /fo list | findstr /C:"Status" /C:"Next Run"
echo.

:: =====================================================
:: DONE
:: =====================================================
echo ============================================
echo    SETUP COMPLETE!
echo ============================================
echo.
echo Your tasks are now scheduled:
echo.
echo   Weekend:      Saturdays at 8:00 AM
echo   Nightly:      Mon-Fri at 9:00 PM
echo   Post-Restart: Daily at 2:15 AM (after IB restart)
echo.
echo To view/modify tasks:
echo   1. Open Task Scheduler (taskschd.msc)
echo   2. Look for "TradeCommand_*" tasks
echo.
echo To manually run a task:
echo   schtasks /run /tn "TradeCommand_Weekend"
echo   schtasks /run /tn "TradeCommand_Nightly"
echo   schtasks /run /tn "TradeCommand_PostRestart"
echo.
echo To disable a task:
echo   schtasks /change /tn "TradeCommand_Nightly" /disable
echo.
echo Press any key to exit...
pause >nul
