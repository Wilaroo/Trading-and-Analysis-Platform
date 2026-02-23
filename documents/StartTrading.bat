@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo ============================================
echo.

:: GitHub repo info
set GITHUB_RAW=https://raw.githubusercontent.com/Wilaroo/Trading-and-Analysis-Platform/main/documents
set DEFAULT_URL=https://system-dashboard-4.preview.emergentagent.com
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
echo [3/5] Starting ngrok tunnel...
echo       Tunnel: https://pseudoaccidentally-linty-addie.ngrok-free.dev
echo.

:: Start ngrok in a new window
start "ngrok Tunnel" cmd /k "ngrok http 11434"

:: Wait for ngrok to initialize
timeout /t 3 /nobreak >nul

echo [4/5] Starting IB Gateway...
:: Start IB Gateway
start "" "C:\Jts\ibgateway\1037\ibgateway.exe"
timeout /t 8 /nobreak >nul

:: Auto-login using VBScript (sends keystrokes)
echo       Attempting auto-login...
echo Set WshShell = CreateObject("WScript.Shell") > "%TEMP%\ib_login.vbs"
echo WScript.Sleep 2000 >> "%TEMP%\ib_login.vbs"
echo WshShell.AppActivate "IB Gateway" >> "%TEMP%\ib_login.vbs"
echo WScript.Sleep 500 >> "%TEMP%\ib_login.vbs"
echo WshShell.SendKeys "esw100000" >> "%TEMP%\ib_login.vbs"
echo WScript.Sleep 300 >> "%TEMP%\ib_login.vbs"
echo WshShell.SendKeys "{TAB}" >> "%TEMP%\ib_login.vbs"
echo WScript.Sleep 300 >> "%TEMP%\ib_login.vbs"
echo WshShell.SendKeys "Socr1025!" >> "%TEMP%\ib_login.vbs"
echo WScript.Sleep 300 >> "%TEMP%\ib_login.vbs"
echo WshShell.SendKeys "{ENTER}" >> "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul

:: Wait for login and dismiss any warnings
timeout /t 5 /nobreak >nul
echo       Dismissing warnings...
echo Set WshShell = CreateObject("WScript.Shell") > "%TEMP%\ib_dismiss.vbs"
echo WshShell.AppActivate "IB Gateway" >> "%TEMP%\ib_dismiss.vbs"
echo WScript.Sleep 500 >> "%TEMP%\ib_dismiss.vbs"
echo WshShell.SendKeys "{ENTER}" >> "%TEMP%\ib_dismiss.vbs"
echo WScript.Sleep 1000 >> "%TEMP%\ib_dismiss.vbs"
echo WshShell.SendKeys "{ENTER}" >> "%TEMP%\ib_dismiss.vbs"
cscript //nologo "%TEMP%\ib_dismiss.vbs"
del "%TEMP%\ib_dismiss.vbs" 2>nul
echo       IB Gateway started!
echo.

echo [5/5] Opening Trading Platform...
timeout /t 2 /nobreak >nul

:: Open browser to trading platform
start "" "%PLATFORM_URL%"

echo.
echo [DONE] Startup Complete!
echo.
echo ============================================
echo    Platform: %PLATFORM_URL%
echo    IMPORTANT: Keep the ngrok window open!
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
