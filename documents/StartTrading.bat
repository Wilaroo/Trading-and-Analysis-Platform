@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo ============================================
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

:: Open browser to trading platform
start "" "https://system-dashboard-4.preview.emergentagent.com"

echo.
echo [4/4] Startup Complete!
echo.
echo ============================================
echo    IMPORTANT: Keep the ngrok window open!
echo    Close it when you're done trading.
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
