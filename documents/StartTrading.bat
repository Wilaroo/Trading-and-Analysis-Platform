@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo         (Updated March 15, 2026)
echo ============================================
echo.
echo    NEW FEATURES IN THIS VERSION:
echo    * AI Insights Dashboard
echo    * Time-Series AI Model (trained!)
echo    * Prediction Tracking System
echo    * Historical Simulation Engine
echo    * Full Trade Consultation Pipeline
echo ============================================
echo.

:: =====================================================
:: CONFIGURATION - EDIT THESE AS NEEDED
:: =====================================================
:: Cloud platform URL
set CLOUD_URL=https://chat-input-debug.preview.emergentagent.com

:: GitHub repo for auto-updates
set GITHUB_RAW=https://raw.githubusercontent.com/Wilaroo/Trading-and-Analysis-Platform/main/documents

:: Script directory (where this bat file is located)
set SCRIPT_DIR=%~dp0

:: IB Gateway settings
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_PORT=4002
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD GOOGL META AMZN JPM

:: Model override (leave empty for auto-detect based on GPU)
set OLLAMA_MODEL_OVERRIDE=

:: =====================================================
:: STEP 1: AUTO-UPDATE FROM GITHUB
:: =====================================================
echo [1/10] Checking for updates from GitHub...

:: Update StartTrading.bat itself
curl -s -f "%GITHUB_RAW%/StartTrading.bat" > "%TEMP%\StartTrading_new.bat" 2>nul
if %errorlevel%==0 (
    fc /b "%~f0" "%TEMP%\StartTrading_new.bat" >nul 2>&1
    if errorlevel 1 (
        echo       [UPDATE] New StartTrading.bat found!
        copy /y "%TEMP%\StartTrading_new.bat" "%~f0" >nul
        del "%TEMP%\StartTrading_new.bat" 2>nul
        echo       Restarting with updated script...
        timeout /t 2 /nobreak >nul
        start "" "%~f0"
        exit
    ) else (
        echo       StartTrading.bat: Up to date
    )
) else (
    echo       StartTrading.bat: Using local (GitHub unreachable)
)
del "%TEMP%\StartTrading_new.bat" 2>nul

:: Update ollama_http.py (try cloud first, then GitHub)
curl -s -f "%CLOUD_URL%/api/scripts/ollama_http.py" > "%SCRIPT_DIR%ollama_http.py.tmp" 2>nul
if %errorlevel%==0 (
    move /y "%SCRIPT_DIR%ollama_http.py.tmp" "%SCRIPT_DIR%ollama_http.py" >nul
    echo       ollama_http.py: Updated from cloud
) else (
    curl -s -f "%GITHUB_RAW%/ollama_http.py" > "%SCRIPT_DIR%ollama_http.py.tmp" 2>nul
    if %errorlevel%==0 (
        move /y "%SCRIPT_DIR%ollama_http.py.tmp" "%SCRIPT_DIR%ollama_http.py" >nul
        echo       ollama_http.py: Updated from GitHub
    ) else (
        del "%SCRIPT_DIR%ollama_http.py.tmp" 2>nul
        echo       ollama_http.py: Using local
    )
)

:: Update ib_data_pusher.py (try cloud first, then GitHub)
curl -s -f "%CLOUD_URL%/api/scripts/ib_data_pusher.py" > "%SCRIPT_DIR%ib_data_pusher.py.tmp" 2>nul
if %errorlevel%==0 (
    move /y "%SCRIPT_DIR%ib_data_pusher.py.tmp" "%SCRIPT_DIR%ib_data_pusher.py" >nul
    echo       ib_data_pusher.py: Updated from cloud
) else (
    curl -s -f "%GITHUB_RAW%/ib_data_pusher.py" > "%SCRIPT_DIR%ib_data_pusher.py.tmp" 2>nul
    if %errorlevel%==0 (
        move /y "%SCRIPT_DIR%ib_data_pusher.py.tmp" "%SCRIPT_DIR%ib_data_pusher.py" >nul
        echo       ib_data_pusher.py: Updated from GitHub
    ) else (
        del "%SCRIPT_DIR%ib_data_pusher.py.tmp" 2>nul
        echo       ib_data_pusher.py: Using local
    )
)
echo.

:: =====================================================
:: STEP 2: DETECT COMPUTER AND GPU
:: =====================================================
echo [2/10] Detecting system...

:: Get computer name
set COMPUTER_NAME=%COMPUTERNAME%
echo       Computer: %COMPUTER_NAME%

:: Detect GPU using nvidia-smi (get VRAM in MB)
set GPU_NAME=Unknown
set GPU_VRAM=0

:: Use PowerShell for more reliable parsing
for /f "usebackq delims=" %%a in (`powershell -command "$gpu = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null; if($gpu) { $parts = $gpu -split ','; Write-Host ($parts[0].Trim()) } else { Write-Host 'No NVIDIA GPU' }"`) do set GPU_NAME=%%a

for /f "usebackq delims=" %%a in (`powershell -command "$gpu = nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null; if($gpu) { Write-Host ([int]$gpu.Trim()) } else { Write-Host '0' }"`) do set GPU_VRAM=%%a

echo       GPU: %GPU_NAME%
echo       VRAM: %GPU_VRAM% MB

:: =====================================================
:: STEP 3: SELECT OPTIMAL MODEL BASED ON GPU
:: =====================================================
echo.
echo [3/10] Selecting AI model for your GPU...

if defined OLLAMA_MODEL_OVERRIDE (
    if not "%OLLAMA_MODEL_OVERRIDE%"=="" (
        set OLLAMA_MODEL=%OLLAMA_MODEL_OVERRIDE%
        echo       Using override: %OLLAMA_MODEL%
        goto model_selected
    )
)

:: Auto-select based on VRAM
set OLLAMA_MODEL=gpt-oss:120b-cloud
echo       Using gpt-oss:120b-cloud (cloud AI for accuracy)
echo       Fallback: llama3:8b (local)

:model_selected
echo.

:: =====================================================
:: STEP 4: INSTALL PYTHON DEPENDENCIES
:: =====================================================
echo [4/10] Checking Python dependencies...

python -c "import ib_insync" >nul 2>&1
if errorlevel 1 (
    echo       Installing ib_insync...
    pip install ib_insync >nul 2>&1
) else (
    echo       ib_insync: OK
)

python -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
    echo       Installing aiohttp...
    pip install aiohttp >nul 2>&1
) else (
    echo       aiohttp: OK
)

python -c "import httpx" >nul 2>&1
if errorlevel 1 (
    echo       Installing httpx...
    pip install httpx >nul 2>&1
) else (
    echo       httpx: OK
)

python -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo       Installing requests...
    pip install requests >nul 2>&1
) else (
    echo       requests: OK
)
echo.

:: =====================================================
:: STEP 5: START OLLAMA
:: =====================================================
echo [5/10] Starting Ollama...

curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama already running!
) else (
    echo       Starting Ollama server...
    start "Ollama Server" cmd /k "set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    echo       Waiting for startup...
    timeout /t 8 /nobreak >nul
)

:: Pre-load model to GPU (only for local models)
if "%OLLAMA_MODEL%"=="gpt-oss:120b-cloud" (
    echo       Cloud model selected - local model preload skipped
) else (
    echo       Loading %OLLAMA_MODEL% to GPU...
    curl -s -X POST http://localhost:11434/api/generate -d "{\"model\":\"%OLLAMA_MODEL%\",\"prompt\":\"hi\",\"stream\":false}" >nul 2>&1
    if %errorlevel%==0 (
        echo       Model ready!
    ) else (
        echo       Model will load on first use
    )
)
echo.

:: =====================================================
:: STEP 6: START IB GATEWAY AND WAIT FOR API PORT
:: =====================================================
echo [6/10] Starting IB Gateway...

if not exist "%IB_GATEWAY_PATH%" (
    echo       [SKIP] IB Gateway not found at:
    echo       %IB_GATEWAY_PATH%
    goto skip_ib_gateway
)

:: First check if port is already listening (IB Gateway fully ready)
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Gateway already running and API ready!
    goto ib_gateway_done
)

:: Check if IB Gateway process is running but port not ready
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I /N "ibgateway.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo       IB Gateway process found but API not ready...
    echo       Waiting 10 seconds to see if it comes up...
    
    :: Wait 10 seconds to see if port comes up
    set QUICK_CHECK=0
)

:quick_port_check
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Gateway API is now ready!
    goto ib_gateway_done
)
set /a QUICK_CHECK+=1
if %QUICK_CHECK% GEQ 5 (
    echo       Port still not ready after 10s - killing and restarting IB Gateway...
    taskkill /F /IM ibgateway.exe >nul 2>&1
    timeout /t 3 /nobreak >nul
    goto start_ib_fresh
)
timeout /t 2 /nobreak >nul
goto quick_port_check

:start_ib_fresh
echo       Starting IB Gateway fresh...
start "" "%IB_GATEWAY_PATH%"
echo       Waiting for IB Gateway window (10 seconds)...
timeout /t 10 /nobreak >nul

:: Auto-login with PAPER TRADING account - FAST VERSION
echo       Fast auto-login to PAPER account...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 800
    echo WshShell.AppActivate "IB Gateway"
    echo WScript.Sleep 400
    echo If Not WshShell.AppActivate^("IB Gateway"^) Then WshShell.AppActivate "IBKR Gateway"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "paperesw100000"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "{TAB}"
    echo WScript.Sleep 150
    echo WshShell.SendKeys "Socr1025!@!?"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul

:: Wait for IB to process login (this takes time for authentication)
echo       Waiting for authentication (10 seconds)...
timeout /t 10 /nobreak >nul

:: Dismiss any warning popups that appear after login
echo       Dismissing any popups...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 300
    echo WshShell.AppActivate "Warning"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "{ENTER}"
    echo WScript.Sleep 400
    echo WshShell.AppActivate "IBKR"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "{ENTER}"
    echo WScript.Sleep 400
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_dismiss.vbs"
cscript //nologo "%TEMP%\ib_dismiss.vbs"
del "%TEMP%\ib_dismiss.vbs" 2>nul

:check_ib_port
:: CRITICAL: Wait for API port to be listening before proceeding
echo       Waiting for IB Gateway API port %IB_PORT%...
set PORT_ATTEMPTS=0

:port_wait_loop
set /a PORT_ATTEMPTS+=1
if %PORT_ATTEMPTS% GTR 30 (
    echo       [WARNING] IB Gateway port %IB_PORT% not responding after 60 seconds
    echo       Please check:
    echo         1. IB Gateway is fully logged in
    echo         2. API Settings: Enable ActiveX and Socket Clients = CHECKED
    echo         3. Socket Port = %IB_PORT%
    echo         4. Read-Only API = UNCHECKED
    echo.
    echo       Press any key to continue anyway, or Ctrl+C to abort...
    pause >nul
    goto ib_gateway_done
)

:: Check if port is listening using netstat
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Gateway API ready on port %IB_PORT%!
    goto ib_gateway_done
)

:: Visual feedback every 5 attempts
set /a MOD=%PORT_ATTEMPTS% %% 5
if %MOD%==0 (
    echo       Still waiting... (attempt %PORT_ATTEMPTS%/30)
)

timeout /t 2 /nobreak >nul
goto port_wait_loop

:ib_gateway_done
echo       IB Gateway ready!

:skip_ib_gateway
echo.

:: =====================================================
:: STEP 7: START IB DATA PUSHER
:: =====================================================
echo [7/10] Starting IB Data Pusher...

:: Kill existing pusher if running (to avoid duplicate connections)
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1

if exist "%SCRIPT_DIR%ib_data_pusher.py" (
    timeout /t 3 /nobreak >nul
    start "IB Data Pusher" cmd /k "title IB Data Pusher && color 0B && echo ============================== && echo   IB Data Pusher Running && echo   Cloud: %CLOUD_URL% && echo   Symbols: %IB_SYMBOLS% && echo ============================== && python "%SCRIPT_DIR%ib_data_pusher.py" --cloud-url %CLOUD_URL% --symbols %IB_SYMBOLS%"
    echo       IB Data Pusher started!
) else (
    echo       [ERROR] ib_data_pusher.py not found
    echo       Download from: %GITHUB_RAW%/ib_data_pusher.py
)
echo.

:: =====================================================
:: STEP 8: START OLLAMA HTTP PROXY
:: =====================================================
echo [8/10] Starting Ollama HTTP Proxy...

:: Kill existing proxy if running
taskkill /F /FI "WINDOWTITLE eq Ollama AI Proxy*" >nul 2>&1

if exist "%SCRIPT_DIR%ollama_http.py" (
    start "Ollama AI Proxy" cmd /k "title Ollama AI Proxy && color 0D && echo ============================================ && echo   Ollama HTTP Proxy (Stable) && echo   Cloud: %CLOUD_URL% && echo   Model: %OLLAMA_MODEL% && echo   No disconnects - HTTP polling! && echo ============================================ && python "%SCRIPT_DIR%ollama_http.py""
    echo       Ollama Proxy started!
) else (
    echo       [ERROR] ollama_http.py not found
    echo       Download from: %GITHUB_RAW%/ollama_http.py
)
echo.

:: =====================================================
:: STEP 9: CHECK AI MODULES STATUS
:: =====================================================
echo [9/10] Checking AI Modules status...

:: Check Time-Series AI Model
curl -s -f -m 10 "%CLOUD_URL%/api/ai-modules/timeseries/status" > "%TEMP%\ts_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"trained\":true" "%TEMP%\ts_check.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       Time-Series AI: TRAINED and READY
    ) else (
        echo       Time-Series AI: Not trained (run training via API)
    )
) else (
    echo       Time-Series AI: Checking...
)
del "%TEMP%\ts_check.tmp" 2>nul

:: Check AI Modules Configuration
curl -s -f -m 10 "%CLOUD_URL%/api/ai-modules/config" > "%TEMP%\ai_check.tmp" 2>nul
if %errorlevel%==0 (
    echo       AI Modules Config: Available
) else (
    echo       AI Modules Config: Starting...
)
del "%TEMP%\ai_check.tmp" 2>nul

:: Check Simulation Engine
curl -s -f -m 10 "%CLOUD_URL%/api/simulation/jobs" > "%TEMP%\sim_check.tmp" 2>nul
if %errorlevel%==0 (
    echo       Simulation Engine: READY
) else (
    echo       Simulation Engine: Starting...
)
del "%TEMP%\sim_check.tmp" 2>nul
echo.

:: =====================================================
:: STEP 10: VERIFY AND LAUNCH
:: =====================================================
echo [10/10] Final verification and launch...
timeout /t 5 /nobreak >nul

:: Check IB Data Pusher connection
set IB_CONNECTED=NO
curl -s -f -m 5 "%CLOUD_URL%/api/ib/pushed-data" > "%TEMP%\ib_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"connected\":true" "%TEMP%\ib_check.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       IB Data Pusher: CONNECTED
        set IB_CONNECTED=YES
    ) else (
        echo       IB Data Pusher: Waiting for connection...
    )
) else (
    echo       IB Data Pusher: Starting...
)
del "%TEMP%\ib_check.tmp" 2>nul

:: Check Ollama HTTP Proxy
curl -s -f -m 5 "%CLOUD_URL%/api/ollama-proxy/status" > "%TEMP%\proxy_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"any_connected\":true" "%TEMP%\proxy_check.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       Ollama Proxy: CONNECTED
    ) else (
        echo       Ollama Proxy: Connecting...
    )
) else (
    echo       Ollama Proxy: Starting...
)
del "%TEMP%\proxy_check.tmp" 2>nul

:: Check Trading Bot Status
curl -s -f -m 5 "%CLOUD_URL%/api/trading-bot/status" > "%TEMP%\bot_check.tmp" 2>nul
if %errorlevel%==0 (
    echo       Trading Bot: ONLINE
) else (
    echo       Trading Bot: Starting...
)
del "%TEMP%\bot_check.tmp" 2>nul
echo.

:: Open browser
echo       Opening platform...
timeout /t 2 /nobreak >nul
start "" "%CLOUD_URL%"

echo.
echo ============================================
echo          STARTUP COMPLETE!
echo ============================================
echo.
echo    Computer: %COMPUTER_NAME%
echo    GPU: %GPU_NAME% (%GPU_VRAM% MB)
echo    AI Model: %OLLAMA_MODEL%
echo.
echo    Platform: %CLOUD_URL%
echo    GitHub: %GITHUB_RAW%
echo.
echo    Running Services:
echo    * Ollama Server (local AI)
echo    * Ollama HTTP Proxy (stable connection)
echo    * IB Data Pusher (market data + stops)
echo    * IB Gateway (broker connection)
echo.
echo    AI FEATURES (March 2026):
echo    * Time-Series AI Model (price prediction)
echo    * Trade Consultation (Bull/Bear debate)
echo    * Risk Manager Agent
echo    * Institutional Flow Tracking
echo    * Prediction Tracking System
echo    * Historical Simulation Engine
echo.
echo    IMPORTANT: Keep all windows open!
echo    The IB Data Pusher window must stay open
echo    for stop-loss monitoring to work!
echo.
echo ============================================
echo.

:: =====================================================
:: HEALTH CHECK LOOP (Optional - runs in background)
:: =====================================================
:health_loop
echo Press any key to run a connection health check...
echo (or close this window to exit)
pause >nul

echo.
echo === CONNECTION HEALTH CHECK ===
echo.

:: Check IB Pushed Data
curl -s -f -m 5 "%CLOUD_URL%/api/ib/pushed-data" > "%TEMP%\health_ib.tmp" 2>nul
if %errorlevel%==0 (
    echo IB Data:
    type "%TEMP%\health_ib.tmp" | findstr /C:"connected" /C:"positions" /C:"quotes"
) else (
    echo IB Data: NOT CONNECTED
)
del "%TEMP%\health_ib.tmp" 2>nul

echo.

:: Check Bot Status
curl -s -f -m 5 "%CLOUD_URL%/api/trading-bot/status" > "%TEMP%\health_bot.tmp" 2>nul
if %errorlevel%==0 (
    echo Bot Status:
    type "%TEMP%\health_bot.tmp" | findstr /C:"running" /C:"open_trades" /C:"mode"
) else (
    echo Bot Status: Unable to check
)
del "%TEMP%\health_bot.tmp" 2>nul

echo.

:: Check AI Modules
curl -s -f -m 5 "%CLOUD_URL%/api/ai-modules/timeseries/status" > "%TEMP%\health_ai.tmp" 2>nul
if %errorlevel%==0 (
    echo AI Model Status:
    type "%TEMP%\health_ai.tmp" | findstr /C:"trained" /C:"version" /C:"accuracy"
) else (
    echo AI Model: Unable to check
)
del "%TEMP%\health_ai.tmp" 2>nul

echo.

:: Check Simulation Jobs
curl -s -f -m 5 "%CLOUD_URL%/api/simulation/jobs?limit=3" > "%TEMP%\health_sim.tmp" 2>nul
if %errorlevel%==0 (
    echo Recent Simulations:
    type "%TEMP%\health_sim.tmp" | findstr /C:"status" /C:"total_trades" /C:"win_rate"
) else (
    echo Simulations: Unable to check
)
del "%TEMP%\health_sim.tmp" 2>nul

echo.
echo ================================
echo.

goto health_loop
