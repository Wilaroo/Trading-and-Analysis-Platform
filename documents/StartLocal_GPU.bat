@echo off
title TradeCommand - Local Mode (GPU Enabled)
color 0A

echo ============================================
echo    TradeCommand - FULL LOCAL MODE
echo    Backend:  localhost:8001
echo    Frontend: localhost:3000
echo    GPU:      RTX 5060 Ti Ready
echo ============================================
echo.

:: =====================================================
:: CONFIGURATION - Update this path if needed
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

:: =====================================================
:: STEP 0: PULL LATEST FROM GITHUB
:: =====================================================
echo [0/9] Pulling latest code from GitHub...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    if %errorlevel%==0 (
        echo       Code updated!
    ) else (
        echo       [INFO] Using existing code (no changes or offline)
    )
) else (
    echo       [SKIP] Not a git repository
)
popd
echo.

:: =====================================================
:: STEP 1: CHECK PREREQUISITES
:: =====================================================
echo [1/9] Checking prerequisites...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo       [ERROR] Python not found!
    pause
    exit /b 1
)
echo       Python: OK

where yarn >nul 2>&1
if %errorlevel% neq 0 (
    echo       Yarn not found, installing...
    npm install -g yarn
)
echo       Yarn: OK

:: Check GPU
python -c "import torch; exit(0 if torch.cuda.is_available() else 1)" 2>nul
if %errorlevel%==0 (
    echo       GPU: Detected!
) else (
    echo       GPU: Not configured (run InstallML_GPU.bat first)
)

:: Check LightGBM GPU support
python -c "import lightgbm as lgb; p={'device':'gpu','gpu_platform_id':0,'gpu_device_id':0,'verbose':-1}; lgb.Booster(p)" 2>nul
if %errorlevel%==0 (
    echo       LightGBM: GPU ENABLED
) else (
    python -c "import lightgbm" >nul 2>&1
    if %errorlevel%==0 (
        echo       LightGBM: CPU only (run InstallML_GPU.bat for GPU)
    ) else (
        echo       LightGBM: MISSING (run InstallML_GPU.bat)
    )
)
echo.

:: =====================================================
:: STEP 2: START BACKEND
:: =====================================================
echo [2/9] Starting Backend...

:: Kill existing backend if running
taskkill /F /FI "WINDOWTITLE eq TradeCommand Backend*" >nul 2>&1

:: Check for .env
if not exist "%BACKEND_DIR%\.env" (
    echo       [ERROR] Backend .env not found!
    pause
    exit /b 1
)

:: Start backend with GPU environment variables
start "TradeCommand Backend" cmd /k "title TradeCommand Backend - localhost:8001 && color 0E && cd /d %BACKEND_DIR% && set CUDA_VISIBLE_DEVICES=0 && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
echo       Backend starting on port 8001...
echo.

:: Wait for backend to initialize
timeout /t 8 /nobreak >nul

:: =====================================================
:: STEP 3: CONFIGURE FRONTEND FOR LOCAL
:: =====================================================
echo [3/9] Configuring Frontend for local...

:: Create local .env
echo REACT_APP_BACKEND_URL=http://localhost:8001> "%FRONTEND_DIR%\.env"
echo DANGEROUSLY_DISABLE_HOST_CHECK=true>> "%FRONTEND_DIR%\.env"
echo FAST_REFRESH=false>> "%FRONTEND_DIR%\.env"
echo       Frontend configured for localhost
echo.

:: =====================================================
:: STEP 4: START FRONTEND
:: =====================================================
echo [4/9] Starting Frontend...

:: Kill existing frontend if running
taskkill /F /FI "WINDOWTITLE eq TradeCommand Frontend*" >nul 2>&1

:: Check if node_modules exists
pushd "%FRONTEND_DIR%"
if not exist "node_modules" (
    echo       Installing dependencies (first time, please wait)...
    yarn install
)
popd

:: Start frontend
start "TradeCommand Frontend" cmd /k "title TradeCommand Frontend - localhost:3000 && color 0B && cd /d %FRONTEND_DIR% && yarn start"
echo       Frontend starting on port 3000...
echo.

:: =====================================================
:: STEP 5: START OLLAMA
:: =====================================================
echo [5/9] Starting Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo       Ollama already running!
) else (
    echo       Starting Ollama server...
    start "Ollama Server" cmd /k "title Ollama Server && color 0D && set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    timeout /t 5 /nobreak >nul
)
echo.

:: =====================================================
:: STEP 6: START IB GATEWAY
:: =====================================================
echo [6/9] Checking IB Gateway...

:: Check if IB Gateway is already running
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo       IB Gateway already running on port %IB_PORT%!
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
    echo       Update IB_GATEWAY_PATH in this script if needed
)

:start_pusher
echo.

:: =====================================================
:: STEP 7: START IB DATA PUSHER
:: =====================================================
echo [7/9] Starting IB Data Pusher...

:: Kill existing pusher if running
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%SCRIPTS_DIR%\ib_data_pusher.py" (
    start "IB Data Pusher (Local)" cmd /k "title IB Data Pusher (LOCAL) && color 0C && cd /d %SCRIPTS_DIR% && python ib_data_pusher.py --cloud-url http://localhost:8001 --symbols %IB_SYMBOLS%"
    echo       IB Data Pusher started (LOCAL mode)
) else (
    echo       [WARN] ib_data_pusher.py not found at %SCRIPTS_DIR%
)
echo.

:: =====================================================
:: STEP 8: WAIT AND OPEN BROWSER
:: =====================================================
echo [8/9] Waiting for services to start...
echo.
echo ============================================
echo    Services Starting...
echo ============================================
echo.
echo    Backend:  http://localhost:8001
echo    Frontend: http://localhost:3000
echo    Ollama:   http://localhost:11434
echo    IB Data:  Connected to local backend
echo.
echo    ML Training: Available (GPU accelerated)
echo.
echo    Waiting 25 seconds...
timeout /t 25 /nobreak >nul

:: Open browser
start http://localhost:3000

echo.
echo ============================================
echo         LOCAL MODE RUNNING!
echo ============================================
echo.
echo    Press any key to run health check...
pause >nul

:health_loop
cls
echo.
echo ============================================
echo         HEALTH CHECK
echo ============================================
echo.
echo Backend Status:
curl -s http://localhost:8001/api/health 2>nul
echo.
echo.
echo Ollama Status:
curl -s http://localhost:11434/api/tags >nul 2>&1 && echo Ollama: Running || echo Ollama: Not running
echo.
echo IB Gateway Status:
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1 && echo IB Gateway: Connected on port %IB_PORT% || echo IB Gateway: Not connected
echo.
echo GPU Status:
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0)}' if torch.cuda.is_available() else '')" 2>nul
python -c "import lightgbm as lgb; p={'device':'gpu','gpu_platform_id':0,'gpu_device_id':0,'verbose':-1}; lgb.Booster(p); print('LightGBM GPU: ENABLED')" 2>nul || echo LightGBM GPU: DISABLED (CPU mode)
echo.
echo ============================================
echo Press any key for another check, or close this window
pause >nul
goto health_loop
