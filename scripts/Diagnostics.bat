@echo off
title TradeCommand Diagnostics
color 0E

echo ============================================
echo    TradeCommand Diagnostics
echo ============================================
echo.

set CLOUD_URL=https://finbert-scheduler.preview.emergentagent.com

echo [1] Checking Local Ollama...
curl -s http://localhost:11434/api/tags > "%TEMP%\ollama_check.tmp" 2>&1
if %errorlevel%==0 (
    echo     STATUS: RUNNING
    echo     Models found:
    type "%TEMP%\ollama_check.tmp"
) else (
    echo     STATUS: NOT RUNNING
    echo.
    echo     FIX: Start Ollama with:
    echo          set OLLAMA_HOST=0.0.0.0
    echo          set OLLAMA_ORIGINS=*
    echo          ollama serve
)
del "%TEMP%\ollama_check.tmp" 2>nul
echo.

echo [2] Checking Cloud Connection...
curl -s -f "%CLOUD_URL%/api/health" > "%TEMP%\cloud_check.tmp" 2>&1
if %errorlevel%==0 (
    echo     STATUS: CONNECTED
) else (
    echo     STATUS: CANNOT REACH
    echo     Check your internet connection
)
del "%TEMP%\cloud_check.tmp" 2>nul
echo.

echo [3] Checking Ollama Proxy Status...
curl -s "%CLOUD_URL%/api/ollama-proxy/status"
echo.
echo.

echo [4] Checking IB Connection...
curl -s "%CLOUD_URL%/api/ib/status"
echo.
echo.

echo [5] Pulling Required Model (if missing)...
echo     Checking for llama3:8b...
ollama list 2>nul | findstr /C:"llama3:8b" >nul
if %errorlevel%==0 (
    echo     Model llama3:8b found!
) else (
    echo     Model not found. Pull with:
    echo          ollama pull llama3:8b
)
echo.

echo ============================================
echo    Summary:
echo ============================================
echo    1. Make sure Ollama is running (ollama serve)
echo    2. Make sure you have at least one model (ollama pull llama3:8b)
echo    3. Run StartTrading.bat to connect everything
echo ============================================
echo.
pause
