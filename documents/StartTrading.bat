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
set CLOUD_URL=https://local-ai-trading.preview.emergentagent.com
set SCRIPT_DIR=%~dp0

:: IB Gateway settings
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD

:: Model override (leave empty for auto-detect based on GPU)
set OLLAMA_MODEL_OVERRIDE=

:: =====================================================
:: STEP 1: AUTO-UPDATE SCRIPTS FROM CLOUD
:: =====================================================
echo [1/8] Checking for script updates from cloud...

:: Update StartTrading.bat
curl -s -f "%CLOUD_URL%/api/scripts/StartTrading.bat" > "%TEMP%\StartTrading_new.bat" 2>nul
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
        echo       StartTrading.bat is up to date!
    )
) else (
    echo       Could not check for updates (using local version)
)
del "%TEMP%\StartTrading_new.bat" 2>nul

:: Update ollama_http.py (stable HTTP proxy)
curl -s -f "%CLOUD_URL%/api/scripts/ollama_http.py" > "%SCRIPT_DIR%ollama_http.py" 2>nul
if %errorlevel%==0 (
    echo       ollama_http.py updated!
) else (
    echo       ollama_http.py: using local version
)

:: Update ib_data_pusher.py
curl -s -f "%CLOUD_URL%/api/scripts/ib_data_pusher.py" > "%SCRIPT_DIR%ib_data_pusher.py" 2>nul
if %errorlevel%==0 (
    echo       ib_data_pusher.py updated!
) else (
    echo       ib_data_pusher.py: using local version
)
echo.

:: =====================================================
:: STEP 2: DETECT COMPUTER AND GPU
:: =====================================================
echo [2/8] Detecting computer and GPU...

:: Get computer name
set COMPUTER_NAME=%COMPUTERNAME%
echo       Computer: %COMPUTER_NAME%

:: Detect GPU using nvidia-smi
set GPU_NAME=Unknown
set GPU_VRAM=0
for /f "tokens=1,2 delims=," %%a in ('nvidia-smi --query-gpu^=name^,memory.total --format^=csv^,noheader^,nounits 2^>nul') do (
    set GPU_NAME=%%a
    set /a GPU_VRAM=%%b
)

:: Trim spaces
for /f "tokens=* delims= " %%a in ("%GPU_NAME%") do set GPU_NAME=%%a
echo       GPU: %GPU_NAME%
echo       VRAM: %GPU_VRAM% MB

:: =====================================================
:: STEP 3: SELECT OPTIMAL MODEL BASED ON GPU
:: =====================================================
echo.
echo [3/8] Selecting optimal AI model...

if defined OLLAMA_MODEL_OVERRIDE (
    set OLLAMA_MODEL=%OLLAMA_MODEL_OVERRIDE%
    echo       Using override: %OLLAMA_MODEL%
) else (
    :: Auto-select based on VRAM
    :: 16GB+ VRAM: Use deepseek-r1:8b or qwen2.5:14b (best quality)
    :: 8-16GB VRAM: Use qwen2.5:7b (good balance)
    :: 6-8GB VRAM: Use qwen2.5:7b with some CPU offload
    :: 4-6GB VRAM: Use gemma3:4b or qwen2.5:3b
    :: <4GB VRAM: Use qwen2.5:1.5b
    
    if %GPU_VRAM% GEQ 16000 (
        set OLLAMA_MODEL=deepseek-r1:8b
        echo       16GB+ VRAM - Using deepseek-r1:8b (best reasoning)
    ) else if %GPU_VRAM% GEQ 12000 (
        set OLLAMA_MODEL=qwen2.5:14b
        echo       12GB+ VRAM - Using qwen2.5:14b (excellent)
    ) else if %GPU_VRAM% GEQ 8000 (
        set OLLAMA_MODEL=qwen2.5:7b
        echo       8GB+ VRAM - Using qwen2.5:7b (great balance)
    ) else if %GPU_VRAM% GEQ 6000 (
        set OLLAMA_MODEL=qwen2.5:7b
        echo       6GB+ VRAM - Using qwen2.5:7b (with CPU assist)
    ) else if %GPU_VRAM% GEQ 4000 (
        set OLLAMA_MODEL=gemma3:4b
        echo       4GB+ VRAM - Using gemma3:4b (efficient)
    ) else (
        set OLLAMA_MODEL=qwen2.5:1.5b
        echo       Low VRAM - Using qwen2.5:1.5b (lightweight)
    )
)
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
    echo       Waiting for Ollama to start...
    timeout /t 8 /nobreak >nul
)

:: Pre-load model to GPU
echo       Pre-loading %OLLAMA_MODEL% to GPU...
curl -s -X POST http://localhost:11434/api/generate -d "{\"model\":\"%OLLAMA_MODEL%\",\"prompt\":\"hi\",\"stream\":false}" >nul 2>&1
if %errorlevel%==0 (
    echo       Model loaded and ready!
) else (
    echo       Model will load on first use
    echo       (If missing, run: ollama pull %OLLAMA_MODEL%)
)
echo.

:: =====================================================
:: STEP 5: START IB GATEWAY
:: =====================================================
echo [5/8] Starting IB Gateway...

if exist "%IB_GATEWAY_PATH%" (
    start "" "%IB_GATEWAY_PATH%"
    echo       Waiting for IB Gateway to load...
    timeout /t 12 /nobreak >nul

    :: Auto-login
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

    :: Wait and dismiss warnings
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
    echo       [SKIP] IB Gateway not found
    echo       Path: %IB_GATEWAY_PATH%
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
    timeout /t 5 /nobreak >nul
    start "IB Data Pusher" cmd /k "title IB Data Pusher - KEEP OPEN && color 0B && echo ============================== && echo   IB Data Pusher Running && echo   Cloud: %CLOUD_URL% && echo   Symbols: %IB_SYMBOLS% && echo ============================== && python "%SCRIPT_DIR%ib_data_pusher.py" --cloud-url %CLOUD_URL% --symbols %IB_SYMBOLS%"
    timeout /t 3 /nobreak >nul
    echo       IB Data Pusher started!
) else (
    echo       [SKIP] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 7: START OLLAMA HTTP PROXY (STABLE!)
:: =====================================================
echo [7/8] Starting Ollama HTTP Proxy (Stable Connection)...

:: Check dependencies
python -c "import httpx" >nul 2>&1
if errorlevel 1 (
    echo       Installing httpx...
    pip install httpx >nul 2>&1
)

if exist "%SCRIPT_DIR%ollama_http.py" (
    start "Ollama HTTP Proxy" cmd /k "title Ollama AI Proxy - KEEP OPEN && color 0D && echo ============================================ && echo   Ollama HTTP Proxy (Stable) && echo   Cloud: %CLOUD_URL% && echo   Model: %OLLAMA_MODEL% && echo   Connection: HTTP Polling (no disconnects!) && echo ============================================ && python "%SCRIPT_DIR%ollama_http.py""
    timeout /t 3 /nobreak >nul
    echo       Ollama HTTP Proxy started!
) else (
    echo       [ERROR] ollama_http.py not found!
    echo       Creating it now...
    (
    echo import asyncio, json, subprocess, sys, logging, time
    echo from datetime import datetime
    echo logging.basicConfig^(level=logging.INFO, format='%%(asctime)s [%%(levelname)s] %%(message)s', datefmt='%%H:%%M:%%S'^)
    echo logger = logging.getLogger^(__name__^)
    echo try:
    echo     import httpx
    echo except ImportError:
    echo     subprocess.check_call^([sys.executable, "-m", "pip", "install", "httpx"]^)
    echo     import httpx
    echo CLOUD_URL = "%CLOUD_URL%"
    echo OLLAMA_URL = "http://localhost:11434"
    echo class OllamaProxyHTTP:
    echo     def __init__^(self^):
    echo         self.session_id = f"proxy_{int^(time.time^(^)^)}_{id^(self^)}"
    echo     async def check_ollama^(self^):
    echo         try:
    echo             async with httpx.AsyncClient^(timeout=5.0^) as client:
    echo                 r = await client.get^(f"{OLLAMA_URL}/api/tags"^)
    echo                 if r.status_code == 200:
    echo                     return {"available": True, "models": [m['name'] for m in r.json^(^).get^('models', []^)]}
    echo         except Exception as e:
    echo             logger.error^(f"Ollama check failed: {e}"^)
    echo         return {"available": False, "models": []}
    echo     async def call_ollama^(self, request^):
    echo         try:
    echo             async with httpx.AsyncClient^(timeout=180.0^) as client:
    echo                 r = await client.post^(f"{OLLAMA_URL}/api/chat", json=request^)
    echo                 if r.status_code == 200:
    echo                     return {"success": True, "response": r.json^(^)}
    echo         except Exception as e:
    echo             return {"success": False, "error": str^(e^)}
    echo         return {"success": False, "error": "Failed"}
    echo     async def register^(self^):
    echo         try:
    echo             status = await self.check_ollama^(^)
    echo             async with httpx.AsyncClient^(timeout=10.0^) as client:
    echo                 r = await client.post^(f"{CLOUD_URL}/api/ollama-proxy/register", json={"session_id": self.session_id, "ollama_status": status, "timestamp": datetime.now^(^).isoformat^(^)}^)
    echo                 if r.status_code == 200:
    echo                     logger.info^(f"REGISTERED! Models: {status['models']}"^)
    echo                     return True
    echo         except Exception as e:
    echo             logger.error^(f"Registration error: {e}"^)
    echo         return False
    echo     async def poll^(self^):
    echo         try:
    echo             async with httpx.AsyncClient^(timeout=30.0^) as client:
    echo                 r = await client.get^(f"{CLOUD_URL}/api/ollama-proxy/poll", params={"session_id": self.session_id}^)
    echo                 if r.status_code == 200:
    echo                     return r.json^(^).get^("requests", []^)
    echo         except:
    echo             pass
    echo         return []
    echo     async def respond^(self, rid, result^):
    echo         try:
    echo             async with httpx.AsyncClient^(timeout=10.0^) as client:
    echo                 await client.post^(f"{CLOUD_URL}/api/ollama-proxy/response", json={"session_id": self.session_id, "request_id": rid, "result": result}^)
    echo         except:
    echo             pass
    echo     async def heartbeat^(self^):
    echo         while True:
    echo             try:
    echo                 async with httpx.AsyncClient^(timeout=5.0^) as client:
    echo                     await client.post^(f"{CLOUD_URL}/api/ollama-proxy/heartbeat", json={"session_id": self.session_id, "ollama_status": await self.check_ollama^(^)}^)
    echo             except:
    echo                 pass
    echo             await asyncio.sleep^(10^)
    echo     async def run^(self^):
    echo         while not await self.register^(^):
    echo             await asyncio.sleep^(5^)
    echo         asyncio.create_task^(self.heartbeat^(^)^)
    echo         logger.info^("READY - Waiting for AI requests..."^)
    echo         while True:
    echo             for req in await self.poll^(^):
    echo                 rid = req.get^("request_id"^)
    echo                 logger.info^(f">>> Processing: {rid}"^)
    echo                 result = await self.call_ollama^(req.get^("request", {}^)^)
    echo                 logger.info^(f"<<< Done: {rid} {'OK' if result.get^('success'^) else 'FAILED'}"^)
    echo                 await self.respond^(rid, result^)
    echo             await asyncio.sleep^(1^)
    echo async def main^(^):
    echo     print^("=" * 50^)
    echo     print^("  OLLAMA PROXY ^(Stable HTTP^)"^)
    echo     print^("=" * 50^)
    echo     print^(f"  Cloud: {CLOUD_URL}"^)
    echo     print^("  Keep this window open!"^)
    echo     print^("=" * 50^)
    echo     await OllamaProxyHTTP^(^).run^(^)
    echo if __name__ == "__main__":
    echo     try:
    echo         asyncio.run^(main^(^)^)
    echo     except KeyboardInterrupt:
    echo         print^("\nStopped."^)
    ) > "%SCRIPT_DIR%ollama_http.py"
    echo       Created ollama_http.py!
    start "Ollama HTTP Proxy" cmd /k "title Ollama AI Proxy - KEEP OPEN && color 0D && python "%SCRIPT_DIR%ollama_http.py""
    timeout /t 3 /nobreak >nul
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
        echo       Ollama Proxy: CONNECTED (using local GPU!)
    ) else (
        echo       Ollama Proxy: Connecting...
    )
) else (
    echo       Ollama Proxy: Starting...
)
del "%TEMP%\proxy_check.tmp" 2>nul

:: Check IB Data Pusher
curl -s -f -m 5 "%CLOUD_URL%/api/ib/status" > "%TEMP%\ib_check.tmp" 2>nul
if %errorlevel%==0 (
    findstr /C:"\"connected\":true" "%TEMP%\ib_check.tmp" >nul 2>&1
    if %errorlevel%==0 (
        echo       IB Gateway: CONNECTED
    ) else (
        echo       IB Gateway: Waiting for connection...
    )
) else (
    echo       IB Gateway: Cloud checking...
)
del "%TEMP%\ib_check.tmp" 2>nul
echo.

:: Open browser
echo       Opening Trading Platform...
timeout /t 2 /nobreak >nul
start "" "%CLOUD_URL%"

echo.
echo ============================================
echo    STARTUP COMPLETE!
echo ============================================
echo.
echo    Computer: %COMPUTER_NAME%
echo    GPU: %GPU_NAME% (%GPU_VRAM% MB)
echo    AI Model: %OLLAMA_MODEL%
echo.
echo    Platform: %CLOUD_URL%
echo.
echo    Services:
echo    [*] Ollama HTTP Proxy - Stable, no disconnects!
echo    [*] IB Data Pusher - Live market data
echo    [*] Ollama Server - Local AI on GPU
echo.
echo    KEEP ALL WINDOWS OPEN while trading!
echo.
echo ============================================
echo.
echo Press any key to close this window...
pause >nul
