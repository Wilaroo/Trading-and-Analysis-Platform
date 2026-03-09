@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo          (Optimized March 2026)
echo ============================================
echo.

:: GitHub repo info
set GITHUB_RAW=https://raw.githubusercontent.com/Wilaroo/Trading-and-Analysis-Platform/main/documents
set DEFAULT_URL=https://smb-trading-fix.preview.emergentagent.com
set PLATFORM_URL=%DEFAULT_URL%
set SCRIPT_DIR=%~dp0

:: =====================================================
:: CONFIGURATION - Edit these for your setup
:: =====================================================
:: Ollama model - RTX 5060 (8GB VRAM) can handle these well:
:: Options: llama3:8b (recommended), mistral:7b (fast reasoning), llama3.1:8b (newer)
set OLLAMA_MODEL=llama3:8b

:: GPU layers - set to 35 for RTX 5060 (uses GPU for most layers)
set OLLAMA_GPU_LAYERS=35

:: Symbols to track via IB Data Pusher (space-separated)
:: Core market + your active trading tickers
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD

:: IB Gateway path (update if different)
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe

:: =====================================================

:: Self-update check (downloads latest bat file if changed)
echo [0/8] Checking for script updates...
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
echo [1/8] Fetching latest deployment URL...
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

:: Check/Start Ollama with GPU optimization
echo [2/8] Starting Ollama (GPU accelerated - RTX 5060)...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama already running!
) else (
    echo       Starting Ollama with GPU acceleration...
    :: OLLAMA_HOST: Allow external connections
    :: OLLAMA_ORIGINS: Allow cross-origin requests  
    :: GPU acceleration is automatic with NVIDIA drivers
    start "Ollama Server" cmd /k "set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    echo       Waiting for Ollama to start...
    timeout /t 8 /nobreak >nul
)

:: Pre-load the model to GPU (so first chat is instant)
echo       Pre-loading model: %OLLAMA_MODEL% to GPU...
curl -s -X POST http://localhost:11434/api/generate -d "{\"model\":\"%OLLAMA_MODEL%\",\"prompt\":\"hello\",\"stream\":false}" >nul 2>&1
if %errorlevel%==0 (
    echo       Model loaded to GPU and ready!
) else (
    echo       Model will load on first use (may need: ollama pull %OLLAMA_MODEL%)
)
echo.

:: START IB GATEWAY FIRST (before ngrok to avoid focus issues)
echo [3/8] Starting IB Gateway...
if exist "%IB_GATEWAY_PATH%" (
    start "" "%IB_GATEWAY_PATH%"
    echo       Waiting for IB Gateway to load...
    timeout /t 12 /nobreak >nul

    :: Auto-login using VBScript
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
) else (
    echo       [SKIP] IB Gateway not found at: %IB_GATEWAY_PATH%
    echo       Update IB_GATEWAY_PATH in this script if needed
)
echo.

:: NOW start ngrok (after IB Gateway is logged in)
echo [4/8] Starting ngrok tunnels...

:: Create ngrok config for tunnels
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
echo [5/8] Setting up IB Data Pusher...

:: Download latest ib_data_pusher.py from GitHub
echo       Downloading latest ib_data_pusher.py...
curl -s -f "%GITHUB_RAW%/ib_data_pusher.py" > "%SCRIPT_DIR%ib_data_pusher.py" 2>nul
if %errorlevel%==0 (
    echo       Downloaded latest pusher script!
) else (
    if exist "%SCRIPT_DIR%ib_data_pusher.py" (
        echo       Could not download update, using existing local copy
    ) else (
        echo       [ERROR] Cannot download ib_data_pusher.py and no local copy found!
        goto skip_pusher
    )
)

:: Check/install Python dependencies
echo       Checking Python dependencies...
python -c "import ib_insync" >nul 2>&1
if errorlevel 1 (
    echo       Installing ib_insync...
    pip install ib_insync >nul 2>&1
)

python -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
    echo       Installing aiohttp...
    pip install aiohttp >nul 2>&1
)
echo       Dependencies OK!

:: Wait for IB Gateway API to be ready
echo       Waiting for IB Gateway API...
timeout /t 5 /nobreak >nul

:: Start the pusher with expanded symbol list
echo       Starting IB Data Pusher...
start "IB Data Pusher" cmd /k "title IB Data Pusher - KEEP OPEN && color 0B && echo ============================== && echo   IB Data Pusher Running && echo   Cloud: %PLATFORM_URL% && echo   Symbols: %IB_SYMBOLS% && echo   Press Ctrl+C to stop && echo ============================== && python "%SCRIPT_DIR%ib_data_pusher.py" --cloud-url %PLATFORM_URL% --symbols %IB_SYMBOLS%"
timeout /t 3 /nobreak >nul
echo       IB Data Pusher started!
goto done_pusher

:skip_pusher
echo       [SKIP] IB Data Pusher not started - fix errors above
:done_pusher
echo.

:: ===================== VERIFY CONNECTIONS =====================
echo [6/8] Verifying connections (5 second timeout each)...
timeout /t 3 /nobreak >nul

:: Check Ollama tunnel (with timeout)
echo       Checking Ollama tunnel...
curl -s -f -m 5 "https://pseudoaccidentally-linty-addie.ngrok-free.dev/api/tags" -H "ngrok-skip-browser-warning: true" >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama tunnel: CONNECTED
) else (
    echo       Ollama tunnel: Not responding (will retry in background)
)

:: Check IB Data Pusher (with timeout)
curl -s -f -m 5 "%PLATFORM_URL%/api/ib/pushed-data" > "%TEMP%\pusher_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"connected\":true" "%TEMP%\pusher_check.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       IB Data Pusher: CONNECTED
    ) else (
        echo       IB Data Pusher: Connecting...
    )
) else (
    echo       IB Data Pusher: Cloud not responding (will connect when ready)
)
del "%TEMP%\pusher_check.tmp" 2>nul
echo.

:: ===================== REGISTER OLLAMA WITH CLOUD =====================
echo [7/8] Registering Ollama with cloud platform...
curl -s -m 10 -X POST "%PLATFORM_URL%/api/assistant/configure" ^
    -H "Content-Type: application/json" ^
    -d "{\"ollama_url\":\"https://pseudoaccidentally-linty-addie.ngrok-free.dev\",\"ollama_model\":\"%OLLAMA_MODEL%\"}" >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama registered with cloud!
) else (
    echo       Cloud registration pending (will auto-detect when available)
)
echo.

echo [8/8] Opening Trading Platform...
timeout /t 2 /nobreak >nul
start "" "%PLATFORM_URL%"

echo.
echo ============================================
echo    [DONE] TradeCommand Startup Complete!
echo ============================================
echo.
echo    Platform: %PLATFORM_URL%
echo.
echo    Services Running:
echo    - Ollama: %OLLAMA_MODEL% (GPU accelerated - RTX 5060)
echo      Tunnel: https://pseudoaccidentally-linty-addie.ngrok-free.dev
echo    - IB Gateway: Running on port 4002
echo    - IB Data Pusher: Pushing to cloud
echo    - ngrok: All tunnels active
echo.
echo    Tracked Symbols: %IB_SYMBOLS%
echo.
echo    KEEP ALL WINDOWS OPEN while trading!
echo.
echo    Quick Commands in TradeCommand Chat:
echo    - "deploy the trading bot for XOM CVX CF NTR"
echo    - "bot status"
echo    - "stop the bot"
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
