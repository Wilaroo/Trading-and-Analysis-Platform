@echo off
title TradeCommand - Full Local Mode
color 0A

echo ============================================
echo    TradeCommand - FULL LOCAL MODE
echo    Backend: localhost:8001
echo    Frontend: localhost:3000
echo    No Cloudflare - No Rate Limits!
echo ============================================
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
set SCRIPT_DIR=%~dp0
set REPO_DIR=%SCRIPT_DIR%..
set BACKEND_DIR=%REPO_DIR%\backend
set FRONTEND_DIR=%REPO_DIR%\frontend

:: IB Gateway settings (same as StartTrading.bat)
set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_PORT=4002
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD

:: Local URLs
set LOCAL_BACKEND=http://localhost:8001
set LOCAL_FRONTEND=http://localhost:3000

:: =====================================================
:: STEP 1: CHECK PREREQUISITES
:: =====================================================
echo [1/8] Checking prerequisites...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo       [ERROR] Python not found! Install Python 3.10+
    pause
    exit /b 1
)
echo       Python: OK

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo       [ERROR] Node.js not found! Install Node.js 18+
    pause
    exit /b 1
)
echo       Node.js: OK

where yarn >nul 2>&1
if %errorlevel% neq 0 (
    echo       [WARN] Yarn not found, installing...
    npm install -g yarn
)
echo       Yarn: OK
echo.

:: =====================================================
:: STEP 2: GIT PULL LATEST
:: =====================================================
echo [2/8] Pulling latest code from GitHub...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    if %errorlevel%==0 (
        echo       Code updated!
    ) else (
        echo       [INFO] Using existing code
    )
) else (
    echo       [SKIP] Not a git repository
)
popd
echo.

:: =====================================================
:: STEP 3: INSTALL BACKEND DEPENDENCIES
:: =====================================================
echo [3/8] Checking backend dependencies...
pushd "%BACKEND_DIR%"
if exist "requirements.txt" (
    pip install -r requirements.txt -q 2>nul
    echo       Backend dependencies: OK
) else (
    echo       [WARN] requirements.txt not found
)
popd
echo.

:: =====================================================
:: STEP 4: INSTALL FRONTEND DEPENDENCIES
:: =====================================================
echo [4/8] Checking frontend dependencies...
pushd "%FRONTEND_DIR%"
if exist "package.json" (
    if not exist "node_modules" (
        echo       Installing frontend packages (first time)...
        yarn install
    ) else (
        echo       Frontend dependencies: OK
    )
)
popd
echo.

:: =====================================================
:: STEP 5: START OLLAMA
:: =====================================================
echo [5/8] Starting Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama already running!
) else (
    echo       Starting Ollama server...
    start "Ollama Server" cmd /k "set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    timeout /t 5 /nobreak >nul
)
echo.

:: =====================================================
:: STEP 6: START BACKEND
:: =====================================================
echo [6/8] Starting Backend (localhost:8001)...

:: Kill existing backend if running
taskkill /F /FI "WINDOWTITLE eq Local Backend*" >nul 2>&1

:: Create local .env if needed (uses MongoDB Atlas from existing .env)
pushd "%BACKEND_DIR%"
if not exist ".env" (
    echo       [ERROR] Backend .env not found!
    echo       Please copy .env from your Emergent workspace
    pause
    exit /b 1
)

:: Start backend
start "Local Backend" cmd /k "title Local Backend - localhost:8001 && color 0E && cd /d %BACKEND_DIR% && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
popd
echo       Backend starting on port 8001...
echo.

:: =====================================================
:: STEP 7: START FRONTEND
:: =====================================================
echo [7/8] Starting Frontend (localhost:3000)...

:: Kill existing frontend if running
taskkill /F /FI "WINDOWTITLE eq Local Frontend*" >nul 2>&1

:: Update frontend .env for local backend
pushd "%FRONTEND_DIR%"

:: Backup original .env and create local version
if not exist ".env.cloud.backup" (
    if exist ".env" copy ".env" ".env.cloud.backup" >nul
)

:: Create local .env pointing to localhost
echo REACT_APP_BACKEND_URL=http://localhost:8001> ".env.local"
echo DANGEROUSLY_DISABLE_HOST_CHECK=true>> ".env.local"
echo FAST_REFRESH=false>> ".env.local"

:: Use local env
copy /y ".env.local" ".env" >nul

:: Start frontend
start "Local Frontend" cmd /k "title Local Frontend - localhost:3000 && color 0B && cd /d %FRONTEND_DIR% && yarn start"
popd
echo       Frontend starting on port 3000...
echo.

:: =====================================================
:: STEP 8: START IB GATEWAY AND PUSHER
:: =====================================================
echo [8/8] Starting IB Gateway and Data Pusher...

:: Check if IB Gateway is already running
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Gateway already running!
    goto start_pusher
)

:: Start IB Gateway if path exists
if exist "%IB_GATEWAY_PATH%" (
    echo       Starting IB Gateway...
    start "" "%IB_GATEWAY_PATH%"
    echo       Please log in to IB Gateway manually
    echo       Waiting 30 seconds for login...
    timeout /t 30 /nobreak >nul
) else (
    echo       [SKIP] IB Gateway not found at %IB_GATEWAY_PATH%
)

:start_pusher
:: Start IB Data Pusher pointing to LOCAL backend
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%SCRIPT_DIR%scripts\ib_data_pusher.py" (
    start "IB Data Pusher (Local)" cmd /k "title IB Data Pusher (LOCAL) && color 0C && echo ============================== && echo   IB Data Pusher - LOCAL MODE && echo   Backend: %LOCAL_BACKEND% && echo ============================== && python "%SCRIPT_DIR%scripts\ib_data_pusher.py" --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS%"
    echo       IB Data Pusher started (LOCAL mode)
) else if exist "%SCRIPT_DIR%ib_data_pusher.py" (
    start "IB Data Pusher (Local)" cmd /k "title IB Data Pusher (LOCAL) && color 0C && echo ============================== && echo   IB Data Pusher - LOCAL MODE && echo   Backend: %LOCAL_BACKEND% && echo ============================== && python "%SCRIPT_DIR%ib_data_pusher.py" --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS%"
    echo       IB Data Pusher started (LOCAL mode)
) else (
    echo       [WARN] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: DONE - WAIT FOR SERVICES
:: =====================================================
echo ============================================
echo    STARTING UP - Please wait...
echo ============================================
echo.
echo    Services starting:
echo    * Backend:  %LOCAL_BACKEND%
echo    * Frontend: %LOCAL_FRONTEND%
echo    * Ollama:   http://localhost:11434
echo    * IB Data:  Connected to local backend
echo.
echo    Waiting 20 seconds for services to initialize...
timeout /t 20 /nobreak >nul

:: Open browser
echo    Opening browser...
start "" "%LOCAL_FRONTEND%"

echo.
echo ============================================
echo         LOCAL MODE RUNNING!
echo ============================================
echo.
echo    Frontend: %LOCAL_FRONTEND%
echo    Backend:  %LOCAL_BACKEND%
echo.
echo    Benefits:
echo    * No Cloudflare rate limits
echo    * Faster AI responses
echo    * Direct Ollama connection
echo.
echo    Keep this window open!
echo    Press any key to run health check...
echo ============================================
pause >nul

:health_loop
echo.
echo === LOCAL HEALTH CHECK ===
curl -s "%LOCAL_BACKEND%/api/health" 2>nul && echo.
curl -s "%LOCAL_BACKEND%/api/ib/status" 2>nul | findstr "connected"
curl -s "http://localhost:11434/api/tags" >nul 2>&1 && echo Ollama: OK || echo Ollama: Not running
echo ===========================
echo.
echo Press any key for another health check...
pause >nul
goto health_loop
