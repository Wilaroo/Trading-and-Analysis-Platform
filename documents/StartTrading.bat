@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo ============================================
echo.

:: GitHub repo info
set GITHUB_RAW=https://raw.githubusercontent.com/Wilaroo/Trading-and-Analysis-Platform/main/documents
set DEFAULT_URL=https://ai-scanner-sim.preview.emergentagent.com
set PLATFORM_URL=%DEFAULT_URL%
set SCRIPT_DIR=%~dp0

:: Self-update check (downloads latest bat file if changed)
echo [0/7] Checking for script updates...
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
echo [1/7] Fetching latest deployment URL...
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
echo [2/7] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama is running!
) else (
    echo       Starting Ollama with remote access enabled...
    start "Ollama Server" cmd /k "set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    timeout /t 5 /nobreak >nul
)
echo.

:: START IB GATEWAY FIRST (before ngrok to avoid focus issues)
echo [3/7] Starting IB Gateway...
start "" "C:\Jts\ibgateway\1037\ibgateway.exe"
echo       Waiting for IB Gateway to load...
timeout /t 12 /nobreak >nul

:: Auto-login using VBScript (IB API and Paper Trading should already be selected)
echo       Entering login credentials...
(
echo Set WshShell = CreateObject^("WScript.Shell"^)
echo WScript.Sleep 2000
echo WshShell.AppActivate "IBKR Gateway"
echo WScript.Sleep 1000
echo WshShell.SendKeys "esw100000"
echo WScript.Sleep 500
echo WshShell.SendKeys "{TAB}"
echo WScript.Sleep 400
echo WshShell.SendKeys "Socr1025!"
echo WScript.Sleep 500
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
echo [4/7] Starting ngrok tunnels...

:: Create ngrok config for tunnels (authtoken already saved via ngrok config)
echo       Creating tunnel config...
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
start "ngrok Tunnels" cmd /k "ngrok start --all --config=%USERPROFILE%\AppData\Local\ngrok\ngrok.yml --config=%TEMP%\ngrok_trading.yml"
timeout /t 5 /nobreak >nul
echo.

:: ===================== IB DATA PUSHER SETUP =====================
echo [5/7] Setting up IB Data Pusher...

:: Step 1: Download latest ib_data_pusher.py from GitHub
echo       Downloading latest ib_data_pusher.py...
curl -s -f "%GITHUB_RAW%/ib_data_pusher.py" > "%SCRIPT_DIR%ib_data_pusher.py" 2>nul
if %errorlevel%==0 (
    echo       Downloaded latest pusher script!
) else (
    if exist "%SCRIPT_DIR%ib_data_pusher.py" (
        echo       Could not download update, using existing local copy
    ) else (
        echo       [ERROR] Cannot download ib_data_pusher.py and no local copy found!
        echo       Please manually download from GitHub to: %SCRIPT_DIR%
        goto skip_pusher
    )
)

:: Step 2: Check/install Python dependencies
echo       Checking Python dependencies...
python -c "import ib_insync" >nul 2>&1
if errorlevel 1 (
    echo       Installing ib_insync...
    pip install ib_insync >nul 2>&1
    if errorlevel 1 (
        echo       [ERROR] Failed to install ib_insync
        echo       Run manually: pip install ib_insync
        goto skip_pusher
    )
    echo       ib_insync installed!
) else (
    echo       ib_insync OK
)

python -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
    echo       Installing aiohttp...
    pip install aiohttp >nul 2>&1
    if errorlevel 1 (
        echo       [ERROR] Failed to install aiohttp
        echo       Run manually: pip install aiohttp
        goto skip_pusher
    )
    echo       aiohttp installed!
) else (
    echo       aiohttp OK
)

:: Step 3: Wait a bit for IB Gateway API to be ready
echo       Waiting for IB Gateway API to be ready...
timeout /t 5 /nobreak >nul

:: Step 4: Start the pusher
echo       Starting IB Data Pusher...
start "IB Data Pusher" cmd /k "title IB Data Pusher - KEEP OPEN && color 0B && echo ============================== && echo   IB Data Pusher Running && echo   Cloud: %PLATFORM_URL% && echo   Press Ctrl+C to stop && echo ============================== && python "%SCRIPT_DIR%ib_data_pusher.py" --cloud-url %PLATFORM_URL% --symbols VIX SPY QQQ IWM DIA NVDA AAPL MSFT TSLA AMD"
timeout /t 3 /nobreak >nul
echo       IB Data Pusher started!
goto done_pusher

:skip_pusher
echo       [SKIP] IB Data Pusher not started - fix errors above
:done_pusher
echo.

:: ===================== VERIFY PUSHER CONNECTION =====================
echo [6/7] Verifying IB Data Pusher connection...
:: Wait for pusher to connect and push first data
timeout /t 8 /nobreak >nul

:: Check if cloud backend received data
curl -s -f "%PLATFORM_URL%/api/ib/pushed-data" > "%TEMP%\pusher_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"connected\":true" "%TEMP%\pusher_check.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       IB Data Pusher: CONNECTED - Data flowing to cloud!
    ) else (
        echo       IB Data Pusher: Started but not yet connected
        echo       It may take a few more seconds to establish connection
        echo       Check the "IB Data Pusher" window for status
    )
) else (
    echo       Could not verify pusher connection (cloud may be loading)
)
del "%TEMP%\pusher_check.tmp" 2>nul
echo.

echo [7/7] Opening Trading Platform...
timeout /t 2 /nobreak >nul
start "" "%PLATFORM_URL%"

echo.
echo [DONE] Startup Complete!
echo.
echo ============================================
echo    Platform: %PLATFORM_URL%
echo    
echo    Services Running:
echo    - Ollama: Local AI (tunnel: https://pseudoaccidentally-linty-addie.ngrok-free.dev)
echo    - IB Gateway: Running on port 4002
echo    - IB Data Pusher: Pushing positions/quotes to cloud
echo    - ngrok: Ollama + IB Gateway tunnels active
echo    
echo    KEEP ALL WINDOWS OPEN while trading!
echo    
echo    Symbols tracked: VIX SPY QQQ IWM DIA NVDA AAPL MSFT TSLA AMD
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
