@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo ============================================
echo.

:: GitHub repo info
set GITHUB_RAW=https://raw.githubusercontent.com/Wilaroo/Trading-and-Analysis-Platform/main/documents
set DEFAULT_URL=https://market-intel-bot-8.preview.emergentagent.com
set PLATFORM_URL=%DEFAULT_URL%

:: Self-update check (downloads latest bat file if changed)
echo [0/5] Checking for script updates...
curl -s -f "%GITHUB_RAW%/StartTrading.bat" > "%TEMP%\StartTrading_new.bat" 2>nul
if %errorlevel%==0 (
    fc /b "%~f0" "%TEMP%\StartTrading_new.bat" >nul 2>&1
    if errorlevel 1 (
        echo       New version found! Updating...
        copy /y "%TEMP%\StartTrading_new.bat" "%~f0" >nul
        del "%TEMP%\StartTrading_new.bat" 2>nul
        echo       Restarting with updated script...
        timeout /t 2 /nobreak >nul
        start "" "%~f0"
        exit
    ) else (
        echo       Script is up to date!
    )
) else (
    echo       Could not check for updates (offline?)
)
del "%TEMP%\StartTrading_new.bat" 2>nul
echo.

:: Fetch latest deployment URL from GitHub
echo [1/5] Fetching latest deployment URL...
curl -s -f "%GITHUB_RAW%/current_deployment.txt" > "%TEMP%\deployment_url.tmp" 2>nul
if %errorlevel%==0 (
    set /p PLATFORM_URL=<"%TEMP%\deployment_url.tmp"
    echo       URL: %PLATFORM_URL%
) else (
    echo       Using default URL (GitHub unreachable)
    echo       URL: %DEFAULT_URL%
)
del "%TEMP%\deployment_url.tmp" 2>nul
echo.

:: Check if Ollama is running
echo [2/5] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama is running!
) else (
    echo       Starting Ollama...
    start "" "C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama app.exe"
    timeout /t 5 /nobreak >nul
)
echo.

:: START IB GATEWAY FIRST (before ngrok to avoid focus issues)
echo [3/5] Starting IB Gateway...
start "" "C:\Jts\ibgateway\1037\ibgateway.exe"
echo       Waiting for IB Gateway to load...
timeout /t 12 /nobreak >nul

:: Auto-login using VBScript (sends keystrokes)
echo       Sending login credentials...
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WScript.Sleep 2000
echo WshShell.AppActivate "IBKR Gateway"
echo WScript.Sleep 1500
echo WshShell.SendKeys "esw100000"
echo WScript.Sleep 500
echo WshShell.SendKeys "{TAB}"
echo WScript.Sleep 500
echo WshShell.SendKeys "Socr1025!"
echo WScript.Sleep 500
echo WshShell.SendKeys "{TAB}"
echo WScript.Sleep 300
echo WshShell.SendKeys "{TAB}"
echo WScript.Sleep 300
echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul
echo       Login submitted!

:: Wait for login to process and dismiss warnings
echo       Waiting for login to complete...
timeout /t 10 /nobreak >nul
echo       Dismissing any warnings...
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WScript.Sleep 1000
echo WshShell.AppActivate "IBKR"
echo WScript.Sleep 500
echo WshShell.SendKeys "{ENTER}"
echo WScript.Sleep 2000
echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_dismiss.vbs"
cscript //nologo "%TEMP%\ib_dismiss.vbs"
del "%TEMP%\ib_dismiss.vbs" 2>nul
echo       IB Gateway ready!
echo.

:: NOW start ngrok (after IB Gateway is logged in)
echo [4/5] Starting ngrok tunnels...

:: Create ngrok config for both tunnels
echo       Creating ngrok config...
(
echo version: "2"
echo tunnels:
echo   ollama:
echo     addr: 11434
echo     proto: http
echo     hostname: pseudoaccidentally-linty-addie.ngrok-free.dev
echo   ib-gateway:
echo     addr: 4002
echo     proto: tcp
echo     remote_addr: 5.tcp.ngrok.io:29573
) > "%TEMP%\ngrok_trading.yml"

echo       Ollama tunnel: https://pseudoaccidentally-linty-addie.ngrok-free.dev
echo       IB Gateway tunnel: tcp://5.tcp.ngrok.io:29573
:: Use both default config (has authtoken) and our tunnels config
start "ngrok Tunnels" cmd /k "ngrok start --all --config=%USERPROFILE%\.ngrok2\ngrok.yml --config=%TEMP%\ngrok_trading.yml"
timeout /t 5 /nobreak >nul
echo.

echo [5/5] Opening Trading Platform...
timeout /t 2 /nobreak >nul
start "" "%PLATFORM_URL%"

echo.
echo [DONE] Startup Complete!
echo.
echo ============================================
echo    Platform: %PLATFORM_URL%
echo    
echo    Tunnels Active:
echo    - Ollama: https://pseudoaccidentally-linty-addie.ngrok-free.dev
echo    - IB Gateway: tcp://5.tcp.ngrok.io:29573
echo    
echo    IMPORTANT: Keep the ngrok window open!
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
