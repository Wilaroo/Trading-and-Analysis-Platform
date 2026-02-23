@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo ============================================
echo.

:: Configuration - UPDATE THIS with your GitHub raw URL after first save
set CONFIG_URL=https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/documents/current_deployment.txt
set DEFAULT_URL=https://system-dashboard-4.preview.emergentagent.com
set PLATFORM_URL=%DEFAULT_URL%

:: Try to fetch latest deployment URL from GitHub
echo [0/4] Checking for latest deployment URL...
curl -s -f "%CONFIG_URL%" > "%TEMP%\deployment_url.tmp" 2>nul
if %errorlevel%==0 (
    set /p PLATFORM_URL=<"%TEMP%\deployment_url.tmp"
    echo       Found latest URL from config!
) else (
    echo       Using default URL (update CONFIG_URL in bat file for auto-updates)
)
del "%TEMP%\deployment_url.tmp" 2>nul
echo       URL: %PLATFORM_URL%
echo.

:: Check if Ollama is running
echo [1/4] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama is running!
) else (
    echo       Starting Ollama...
    start "" "C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama app.exe"
    timeout /t 5 /nobreak >nul
)

echo.
echo [2/4] Starting ngrok tunnel...
echo       Your tunnel URL: https://pseudoaccidentally-linty-addie.ngrok-free.dev
echo.

:: Start ngrok in a new window
start "ngrok Tunnel" cmd /k "ngrok http 11434"

:: Wait for ngrok to initialize
timeout /t 3 /nobreak >nul

echo [3/4] Opening Trading Platform...
timeout /t 2 /nobreak >nul

:: Open browser to trading platform (uses fetched or default URL)
start "" "%PLATFORM_URL%"

echo.
echo [4/4] Startup Complete!
echo.
echo ============================================
echo    Platform: %PLATFORM_URL%
echo    IMPORTANT: Keep the ngrok window open!
echo    Close it when you're done trading.
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
