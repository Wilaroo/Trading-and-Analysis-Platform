@echo off
title TradeCommand - Ultimate Local Mode
color 0A

echo ============================================
echo    TradeCommand - ULTIMATE LOCAL MODE
echo    Backend:  localhost:8001
echo    Frontend: localhost:3000
echo    GPU:      RTX 5060 Ti Ready
echo    IB:       Auto-Login Enabled
echo ============================================
echo.

:: =====================================================
:: CONFIGURATION - Update these paths if needed
:: =====================================================
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set BACKEND_DIR=%REPO_DIR%\backend
set FRONTEND_DIR=%REPO_DIR%\frontend
set DOCUMENTS_DIR=%REPO_DIR%\documents
set SCRIPTS_DIR=%DOCUMENTS_DIR%\scripts

:: IB Gateway settings
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_PORT=4002
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD

:: IB Paper Trading Credentials
set IB_USERNAME=paperesw100000
set IB_PASSWORD=Socr1025!@!?

:: Local URLs
set LOCAL_BACKEND=http://localhost:8001
set LOCAL_FRONTEND=http://localhost:3000

:: =====================================================
:: STEP 1: PULL LATEST FROM GITHUB
:: =====================================================
echo [1/10] Pulling latest code from GitHub...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    if %errorlevel%==0 (
        echo        Code updated!
    ) else (
        echo        [INFO] Using existing code
    )
) else (
    echo        [SKIP] Not a git repository
)
popd
echo.

:: =====================================================
:: STEP 2: CHECK PREREQUISITES
:: =====================================================
echo [2/10] Checking prerequisites...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo        [ERROR] Python not found!
    pause
    exit /b 1
)
echo        Python: OK

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo        [ERROR] Node.js not found!
    pause
    exit /b 1
)
echo        Node.js: OK

where yarn >nul 2>&1
if %errorlevel% neq 0 (
    echo        Yarn not found, installing...
    npm install -g yarn
)
echo        Yarn: OK

:: Check GPU
python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>nul
if %errorlevel%==0 (
    for /f "delims=" %%a in ('python -c "import torch; print(torch.cuda.get_device_name(0))" 2^>nul') do set GPU_NAME=%%a
    echo        GPU: %GPU_NAME%
) else (
    echo        GPU: Not configured
    set GPU_NAME=None
)
echo.

:: =====================================================
:: STEP 3: START IB GATEWAY FIRST - it takes longest
:: =====================================================
echo [3/10] Launching IB Gateway...

if not exist "%IB_GATEWAY_PATH%" (
    echo        [SKIP] IB Gateway not found
    set IB_STARTED=NO
    goto start_backend
)

:: Check if already running
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        IB Gateway already running!
    set IB_STARTED=YES
    goto start_backend
)

:: Launch IB Gateway - it will load while we start other things
echo        Launching IB Gateway...
start "" "%IB_GATEWAY_PATH%"
set IB_STARTED=LAUNCHING
echo        IB Gateway loading in background...
echo.

:: =====================================================
:: STEP 4: START BACKEND
:: =====================================================
:start_backend
echo [4/10] Starting Backend...

taskkill /F /FI "WINDOWTITLE eq TradeCommand Backend*" >nul 2>&1

if not exist "%BACKEND_DIR%\.env" (
    echo        [ERROR] Backend .env not found!
    pause
    exit /b 1
)

start "TradeCommand Backend" cmd /k "title TradeCommand Backend - localhost:8001 && color 0E && cd /d %BACKEND_DIR% && set CUDA_VISIBLE_DEVICES=0 && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
echo        Backend starting...
timeout /t 5 /nobreak >nul
echo.

:: =====================================================
:: STEP 5: START FRONTEND
:: =====================================================
echo [5/10] Starting Frontend...

taskkill /F /FI "WINDOWTITLE eq TradeCommand Frontend*" >nul 2>&1

:: Configure frontend for localhost
echo REACT_APP_BACKEND_URL=http://localhost:8001> "%FRONTEND_DIR%\.env"
echo DANGEROUSLY_DISABLE_HOST_CHECK=true>> "%FRONTEND_DIR%\.env"
echo FAST_REFRESH=false>> "%FRONTEND_DIR%\.env"

pushd "%FRONTEND_DIR%"
if not exist "node_modules" (
    echo        Installing packages - first time setup...
    yarn install
)
popd

start "TradeCommand Frontend" cmd /k "title TradeCommand Frontend - localhost:3000 && color 0B && cd /d %FRONTEND_DIR% && yarn start"
echo        Frontend starting...
echo.

:: =====================================================
:: STEP 6: START OLLAMA
:: =====================================================
echo [6/10] Starting Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo        Ollama already running!
) else (
    echo        Starting Ollama server...
    start "Ollama Server" cmd /k "title Ollama Server && color 0D && set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    timeout /t 3 /nobreak >nul
)
echo.

:: =====================================================
:: STEP 7: AUTO-LOGIN TO IB GATEWAY
:: =====================================================
echo [7/10] IB Gateway Auto-Login...

if "%IB_STARTED%"=="YES" (
    echo        Already logged in!
    goto start_pusher
)

if "%IB_STARTED%"=="NO" (
    echo        IB Gateway not available
    goto start_pusher
)

:: IB Gateway was launched - now do auto-login
:: Total time since launch: ~15-20 seconds from steps 4-6
echo        Waiting for IB Gateway to be ready...
timeout /t 10 /nobreak >nul

echo        Entering credentials...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 2000
    echo WshShell.AppActivate "IB Gateway"
    echo WScript.Sleep 1000
    echo If Not WshShell.AppActivate^("IB Gateway"^) Then WshShell.AppActivate "IBKR Gateway"
    echo WScript.Sleep 500
    echo WshShell.SendKeys "%IB_USERNAME%"
    echo WScript.Sleep 400
    echo WshShell.SendKeys "{TAB}"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "%IB_PASSWORD%"
    echo WScript.Sleep 400
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul

echo        Waiting for authentication...
timeout /t 12 /nobreak >nul

:: Dismiss popups
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
) > "%TEMP%\ib_dismiss.vbs"
cscript //nologo "%TEMP%\ib_dismiss.vbs"
del "%TEMP%\ib_dismiss.vbs" 2>nul

:: Wait for port
echo        Waiting for API port %IB_PORT%...
set PORT_ATTEMPTS=0

:port_wait
set /a PORT_ATTEMPTS+=1
if %PORT_ATTEMPTS% GTR 20 (
    echo        [WARN] IB Gateway not ready - may need manual login
    goto start_pusher
)

netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        IB Gateway ready on port %IB_PORT%!
    goto start_pusher
)

timeout /t 2 /nobreak >nul
goto port_wait

:: =====================================================
:: STEP 8: START IB DATA PUSHER
:: =====================================================
:start_pusher
echo.
echo [8/10] Starting IB Data Pusher...

taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%SCRIPTS_DIR%\ib_data_pusher.py" (
    start "IB Data Pusher" cmd /k "title IB Data Pusher - LOCAL && color 0C && cd /d %SCRIPTS_DIR% && python ib_data_pusher.py --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS%"
    echo        IB Data Pusher started!
) else if exist "%DOCUMENTS_DIR%\ib_data_pusher.py" (
    start "IB Data Pusher" cmd /k "title IB Data Pusher - LOCAL && color 0C && cd /d %DOCUMENTS_DIR% && python ib_data_pusher.py --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS%"
    echo        IB Data Pusher started!
) else (
    echo        [WARN] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 9: WAIT AND OPEN BROWSER
:: =====================================================
echo [9/10] Finalizing...
echo.
echo        Waiting for all services...
timeout /t 10 /nobreak >nul

:: Open browser
start "" "%LOCAL_FRONTEND%"
echo.

:: =====================================================
:: STEP 10: SHOW STATUS
:: =====================================================
echo ============================================
echo      TRADECOMMAND LOCAL MODE RUNNING!
echo ============================================
echo.
echo    Frontend: %LOCAL_FRONTEND%
echo    Backend:  %LOCAL_BACKEND%
echo    GPU:      %GPU_NAME%
echo.
echo    Running Services:
echo    - Backend with GPU
echo    - Frontend
echo    - Ollama
echo    - IB Gateway
echo    - IB Data Pusher
echo.
echo    Keep all windows open!
echo.
echo ============================================
echo.
echo    Press any key for health check...
pause >nul

:health_loop
cls
echo.
echo ========== HEALTH CHECK ==========
echo.
echo [Backend]
curl -s %LOCAL_BACKEND%/api/health 2>nul || echo Not responding
echo.
echo.
echo [Ollama]
curl -s http://localhost:11434/api/tags >nul 2>&1 && echo Running || echo Not running
echo.
echo [IB Gateway]
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1 && echo Connected on port %IB_PORT% || echo Not connected
echo.
echo [GPU]
python -c "import torch; print('CUDA:', torch.cuda.is_available())" 2>nul
echo.
echo ===================================
echo Press any key for another check...
pause >nul
goto health_loop
