@echo off
title TradeCommand - Ultimate Local Mode
color 0A

echo ============================================
echo    TradeCommand - ULTIMATE LOCAL MODE
echo ============================================
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set BACKEND_DIR=%REPO_DIR%\backend
set FRONTEND_DIR=%REPO_DIR%\frontend
set DOCUMENTS_DIR=%REPO_DIR%\documents
set SCRIPTS_DIR=%DOCUMENTS_DIR%\scripts

set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_PORT=4002
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD

set IB_USERNAME=paperesw100000
set IB_PASSWORD=Socr1025!@!?

set LOCAL_BACKEND=http://localhost:8001
set LOCAL_FRONTEND=http://localhost:3000

:: =====================================================
:: STEP 1: GIT PULL
:: =====================================================
echo [1/8] Pulling latest code...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    echo        Done!
)
popd
echo.

:: =====================================================
:: STEP 2: CHECK PREREQUISITES
:: =====================================================
echo [2/8] Checking prerequisites...
where python >nul 2>&1 && echo        Python: OK || echo        Python: MISSING
where node >nul 2>&1 && echo        Node.js: OK || echo        Node.js: MISSING
where yarn >nul 2>&1 && echo        Yarn: OK || (echo        Installing yarn... && npm install -g yarn)
python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>nul && echo        GPU: Ready || echo        GPU: Not configured
echo.

:: =====================================================
:: STEP 3: IB GATEWAY - COMPLETE LOGIN FIRST
:: =====================================================
echo [3/8] IB Gateway Login...

if not exist "%IB_GATEWAY_PATH%" (
    echo        [SKIP] IB Gateway not found at %IB_GATEWAY_PATH%
    goto after_ib
)

netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        Already logged in and ready!
    goto after_ib
)

:: Step 3a: Open IB Gateway
echo        Opening IB Gateway...
start "" "%IB_GATEWAY_PATH%"

:: Step 3b: Wait 5 seconds for it to load
echo        Waiting 5 seconds for window to load...
timeout /t 5 /nobreak >nul

:: Step 3c: Input credentials
echo        Entering credentials...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 1000
    echo WshShell.AppActivate "IB Gateway"
    echo WScript.Sleep 500
    echo WshShell.SendKeys "%IB_USERNAME%"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{TAB}"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "%IB_PASSWORD%"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul

:: Step 3d: Wait 5 seconds for authentication
echo        Waiting 5 seconds for authentication...
timeout /t 5 /nobreak >nul

:: Step 3e: Close popup
echo        Closing popup...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 500
    echo WshShell.AppActivate "Warning"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{ENTER}"
    echo WScript.Sleep 500
    echo WshShell.AppActivate "IBKR"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{ENTER}"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_popup.vbs"
cscript //nologo "%TEMP%\ib_popup.vbs"
del "%TEMP%\ib_popup.vbs" 2>nul

:: Step 3f: Wait for API port
echo        Waiting for API port %IB_PORT%...
set ATTEMPTS=0
:wait_ib
set /a ATTEMPTS+=1
if %ATTEMPTS% GTR 15 (
    echo        [WARN] Port not ready - may need manual login
    goto after_ib
)
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        IB Gateway ready!
    goto after_ib
)
timeout /t 2 /nobreak >nul
goto wait_ib

:after_ib
echo.

:: =====================================================
:: STEP 4: START BACKEND
:: =====================================================
echo [4/8] Starting Backend...
taskkill /F /FI "WINDOWTITLE eq TradeCommand Backend*" >nul 2>&1
start "TradeCommand Backend" cmd /k "title TradeCommand Backend && color 0E && cd /d %BACKEND_DIR% && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
echo        Backend starting on port 8001...
timeout /t 5 /nobreak >nul
echo.

:: =====================================================
:: STEP 5: START FRONTEND
:: =====================================================
echo [5/8] Starting Frontend...
taskkill /F /FI "WINDOWTITLE eq TradeCommand Frontend*" >nul 2>&1

echo REACT_APP_BACKEND_URL=http://localhost:8001> "%FRONTEND_DIR%\.env"
echo DANGEROUSLY_DISABLE_HOST_CHECK=true>> "%FRONTEND_DIR%\.env"
echo FAST_REFRESH=false>> "%FRONTEND_DIR%\.env"

start "TradeCommand Frontend" cmd /k "title TradeCommand Frontend && color 0B && cd /d %FRONTEND_DIR% && yarn start"
echo        Frontend starting on port 3000...
echo.

:: =====================================================
:: STEP 6: START OLLAMA
:: =====================================================
echo [6/8] Starting Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo        Ollama already running!
) else (
    start "Ollama Server" cmd /k "title Ollama Server && color 0D && set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    echo        Ollama starting...
)
echo.

:: =====================================================
:: STEP 7: START IB DATA PUSHER
:: =====================================================
echo [7/8] Starting IB Data Pusher...
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%SCRIPTS_DIR%\ib_data_pusher.py" (
    start "IB Data Pusher" cmd /k "title IB Data Pusher && color 0C && cd /d %SCRIPTS_DIR% && python ib_data_pusher.py --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS%"
    echo        Data pusher started!
) else (
    echo        [SKIP] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 8: OPEN BROWSER
:: =====================================================
echo [8/8] Opening browser...
timeout /t 15 /nobreak >nul
start "" "%LOCAL_FRONTEND%"

echo.
echo ============================================
echo      ALL SERVICES STARTED!
echo ============================================
echo.
echo    Frontend: %LOCAL_FRONTEND%
echo    Backend:  %LOCAL_BACKEND%
echo.
echo    Press any key for health check...
pause >nul

:health_loop
cls
echo.
echo ========== HEALTH CHECK ==========
echo.
curl -s %LOCAL_BACKEND%/api/health 2>nul || echo Backend: Not responding
echo.
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1 && echo IB Gateway: Connected || echo IB Gateway: Not connected
curl -s http://localhost:11434/api/tags >nul 2>&1 && echo Ollama: Running || echo Ollama: Not running
echo.
echo ===================================
echo Press any key to check again...
pause >nul
goto health_loop
