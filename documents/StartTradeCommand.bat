@echo off
title TradeCommand - Mode Switcher
color 0F

echo ============================================
echo    TradeCommand Mode Switcher
echo ============================================
echo.
echo Choose your mode:
echo.
echo   1. CLOUD MODE (Current: Emergent Preview/Production)
echo      - Uses cloud backend
echo      - Accessible from anywhere
echo      - May have rate limits on preview
echo.
echo   2. LOCAL MODE  
echo      - Runs backend on your PC
echo      - No rate limits
echo      - Faster AI responses
echo      - Only accessible locally
echo.
echo   3. EXIT
echo.
set /p choice="Enter choice (1/2/3): "

if "%choice%"=="1" goto cloud_mode
if "%choice%"=="2" goto local_mode
if "%choice%"=="3" exit
goto :eof

:cloud_mode
echo.
echo Starting CLOUD mode...
call "%~dp0StartTrading.bat"
goto :eof

:local_mode
echo.
echo Starting LOCAL mode...
call "%~dp0StartLocal.bat"
goto :eof
