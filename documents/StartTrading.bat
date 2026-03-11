@echo off
title TradeCommand Startup
color 0A

echo ============================================
echo    TradeCommand Trading Platform Startup
echo         (Updated March 10, 2026)
echo ============================================
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
:: GitHub repo for auto-updates
set GITHUB_RAW=https://raw.githubusercontent.com/Wilaroo/Trading-and-Analysis-Platform/main/documents

:: Cloud platform URL
set CLOUD_URL=https://ib-live-dashboard.preview.emergentagent.com

:: Script directory (where this bat file is located)
set SCRIPT_DIR=%~dp0

:: IB Gateway settings
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD

:: Model override (leave empty for auto-detect based on GPU)
set OLLAMA_MODEL_OVERRIDE=

:: =====================================================
:: STEP 1: AUTO-UPDATE FROM GITHUB
:: =====================================================
echo [1/8] Checking for updates from GitHub...

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
echo [2/8] Detecting system...

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
echo [3/8] Selecting AI model for your GPU...

if defined OLLAMA_MODEL_OVERRIDE (
    if not "%OLLAMA_MODEL_OVERRIDE%"=="" (
        set OLLAMA_MODEL=%OLLAMA_MODEL_OVERRIDE%
        echo       Using override: %OLLAMA_MODEL%
        goto model_selected
    )
)

:: Auto-select based on VRAM (use GOTO to break after first match)
:: Default to gpt-oss:120b-cloud (via ollama_http proxy) for best accuracy
:: Local fallback models based on VRAM
if %GPU_VRAM% GEQ 16000 (
    set OLLAMA_MODEL=gpt-oss:120b-cloud
    echo       16GB+ VRAM - Using gpt-oss:120b-cloud (accurate)
    echo       Fallback: llama3:8b (local)
    goto model_selected
)
if %GPU_VRAM% GEQ 12000 (
    set OLLAMA_MODEL=gpt-oss:120b-cloud
    echo       12GB+ VRAM - Using gpt-oss:120b-cloud (accurate)
    echo       Fallback: llama3:8b (local)
    goto model_selected
)
if %GPU_VRAM% GEQ 8000 (
    set OLLAMA_MODEL=gpt-oss:120b-cloud
    echo       8GB+ VRAM - Using gpt-oss:120b-cloud (accurate)
    echo       Fallback: qwen2.5:7b (local)
    goto model_selected
)
if %GPU_VRAM% GEQ 6000 (
    set OLLAMA_MODEL=llama3:8b
    echo       6GB+ VRAM - Using llama3:8b
    goto model_selected
)
if %GPU_VRAM% GEQ 4000 (
    set OLLAMA_MODEL=gemma3:4b
    echo       4GB+ VRAM - Using gemma3:4b
    goto model_selected
)
set OLLAMA_MODEL=qwen2.5:1.5b
echo       Low VRAM - Using qwen2.5:1.5b

:model_selected
echo.

:: =====================================================
:: STEP 4: START OLLAMA
:: =====================================================
echo [4/8] Starting Ollama...

curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama already running!
) else (
    echo       Starting Ollama server...
    start "Ollama Server" cmd /k "set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    echo       Waiting for startup...
    timeout /t 8 /nobreak >nul
)

:: Pre-load model to GPU
echo       Loading %OLLAMA_MODEL% to GPU...
curl -s -X POST http://localhost:11434/api/generate -d "{\"model\":\"%OLLAMA_MODEL%\",\"prompt\":\"hi\",\"stream\":false}" >nul 2>&1
if %errorlevel%==0 (
    echo       Model ready!
) else (
    echo       Model will load on first use
    echo       (Run: ollama pull %OLLAMA_MODEL%)
)
echo.

:: =====================================================
:: STEP 5: START IB GATEWAY
:: =====================================================
echo [5/8] Starting IB Gateway...

if exist "%IB_GATEWAY_PATH%" (
    start "" "%IB_GATEWAY_PATH%"
    echo       Waiting for IB Gateway...
    timeout /t 12 /nobreak >nul

    :: Auto-login with PAPER TRADING account
    echo       Logging in to PAPER account...
    (
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 2000
    echo WshShell.AppActivate "IBKR Gateway"
    echo WScript.Sleep 1000
    echo WshShell.SendKeys "paperesw100000"
    echo WScript.Sleep 500
    echo WshShell.SendKeys "{TAB}"
    echo WScript.Sleep 400
    echo WshShell.SendKeys "Socr1025!@!?"
    echo WScript.Sleep 500
    echo WshShell.SendKeys "{ENTER}"
    ) > "%TEMP%\ib_login.vbs"
    cscript //nologo "%TEMP%\ib_login.vbs"
    del "%TEMP%\ib_login.vbs" 2>nul

    :: Dismiss warnings
    timeout /t 10 /nobreak >nul
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
    echo       [SKIP] IB Gateway not found at:
    echo              %IB_GATEWAY_PATH%
)
echo.

:: =====================================================
:: STEP 6: START IB DATA PUSHER
:: =====================================================
echo [6/8] Starting IB Data Pusher...

:: Check dependencies
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

if exist "%SCRIPT_DIR%ib_data_pusher.py" (
    timeout /t 3 /nobreak >nul
    start "IB Data Pusher" cmd /k "title IB Data Pusher && color 0B && echo ============================== && echo   IB Data Pusher Running && echo   Cloud: %CLOUD_URL% && echo   Symbols: %IB_SYMBOLS% && echo ============================== && python "%SCRIPT_DIR%ib_data_pusher.py" --cloud-url %CLOUD_URL% --symbols %IB_SYMBOLS%"
    echo       IB Data Pusher started!
) else (
    echo       [SKIP] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 7: START OLLAMA HTTP PROXY
:: =====================================================
echo [7/8] Starting Ollama HTTP Proxy...

:: Check dependencies
python -c "import httpx" >nul 2>&1
if errorlevel 1 (
    echo       Installing httpx...
    pip install httpx >nul 2>&1
)

if exist "%SCRIPT_DIR%ollama_http.py" (
    start "Ollama HTTP Proxy" cmd /k "title Ollama AI Proxy && color 0D && echo ============================================ && echo   Ollama HTTP Proxy (Stable) && echo   Cloud: %CLOUD_URL% && echo   Model: %OLLAMA_MODEL% && echo   No disconnects - HTTP polling! && echo ============================================ && python "%SCRIPT_DIR%ollama_http.py""
    echo       Ollama Proxy started!
) else (
    echo       [ERROR] ollama_http.py not found
    echo       Download from: %GITHUB_RAW%/ollama_http.py
)
echo.

:: =====================================================
:: STEP 8: VERIFY AND LAUNCH
:: =====================================================
echo [8/8] Verifying connections...
timeout /t 5 /nobreak >nul

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

:: Check IB
curl -s -f -m 5 "%CLOUD_URL%/api/ib/status" > "%TEMP%\ib_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"connected\":true" "%TEMP%\ib_check.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       IB Gateway: CONNECTED
    ) else (
        echo       IB Gateway: Connecting...
    )
) else (
    echo       IB Gateway: Waiting...
)
del "%TEMP%\ib_check.tmp" 2>nul
echo.

:: Open browser
echo       Opening platform...
timeout /t 2 /nobreak >nul
start "" "%CLOUD_URL%"

echo.
echo ============================================
echo           STARTUP COMPLETE!
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
echo    * IB Data Pusher (market data)
echo    * IB Gateway (broker connection)
echo.
echo    KEEP ALL WINDOWS OPEN!
echo.
echo ============================================
echo.
pause
