@echo off
title TradeCommand - Ultimate Local Mode (GPU + Auto-Login)
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

:: IB Paper Trading Credentials (for auto-login)
set IB_USERNAME=paperesw100000
set IB_PASSWORD=Socr1025!@!?

:: Local URLs
set LOCAL_BACKEND=http://localhost:8001
set LOCAL_FRONTEND=http://localhost:3000

:: =====================================================
:: STEP 0: PULL LATEST FROM GITHUB
:: =====================================================
echo [0/10] Pulling latest code from GitHub...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    if %errorlevel%==0 (
        echo        Code updated!
    ) else (
        echo        [INFO] Using existing code (no changes or offline)
    )
) else (
    echo        [SKIP] Not a git repository
)
popd
echo.

:: =====================================================
:: STEP 1: CHECK PREREQUISITES
:: =====================================================
echo [1/10] Checking prerequisites...

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
    echo        GPU: Not configured (run InstallML_GPU.bat first)
    set GPU_NAME=None
)
echo.

:: =====================================================
:: STEP 2: INSTALL/CHECK BACKEND DEPENDENCIES
:: =====================================================
echo [2/10] Checking backend dependencies...
pushd "%BACKEND_DIR%"
if exist "requirements.txt" (
    pip install -r requirements.txt -q 2>nul
    echo        Backend dependencies: OK
)
popd
echo.

:: =====================================================
:: STEP 3: START BACKEND
:: =====================================================
echo [3/10] Starting Backend...

:: Kill existing backend if running
taskkill /F /FI "WINDOWTITLE eq TradeCommand Backend*" >nul 2>&1

:: Check for .env
if not exist "%BACKEND_DIR%\.env" (
    echo        [ERROR] Backend .env not found!
    pause
    exit /b 1
)

:: Start backend with GPU environment variables
start "TradeCommand Backend" cmd /k "title TradeCommand Backend - localhost:8001 && color 0E && cd /d %BACKEND_DIR% && set CUDA_VISIBLE_DEVICES=0 && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
echo        Backend starting on port 8001...
echo.

:: Wait for backend to initialize
timeout /t 8 /nobreak >nul

:: =====================================================
:: STEP 4: CONFIGURE AND START FRONTEND
:: =====================================================
echo [4/10] Starting Frontend...

:: Kill existing frontend if running
taskkill /F /FI "WINDOWTITLE eq TradeCommand Frontend*" >nul 2>&1

:: Configure frontend for localhost
echo REACT_APP_BACKEND_URL=http://localhost:8001> "%FRONTEND_DIR%\.env"
echo DANGEROUSLY_DISABLE_HOST_CHECK=true>> "%FRONTEND_DIR%\.env"
echo FAST_REFRESH=false>> "%FRONTEND_DIR%\.env"

:: Check if node_modules exists
pushd "%FRONTEND_DIR%"
if not exist "node_modules" (
    echo        Installing frontend packages (first time, please wait)...
    yarn install
)
popd

:: Start frontend
start "TradeCommand Frontend" cmd /k "title TradeCommand Frontend - localhost:3000 && color 0B && cd /d %FRONTEND_DIR% && yarn start"
echo        Frontend starting on port 3000...
echo.

:: =====================================================
:: STEP 5: START OLLAMA
:: =====================================================
echo [5/10] Starting Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo        Ollama already running!
) else (
    echo        Starting Ollama server...
    start "Ollama Server" cmd /k "title Ollama Server && color 0D && set OLLAMA_HOST=0.0.0.0 && set OLLAMA_ORIGINS=* && ollama serve"
    timeout /t 5 /nobreak >nul
)
echo.

:: =====================================================
:: STEP 6: START IB GATEWAY WITH AUTO-LOGIN
:: =====================================================
echo [6/10] Starting IB Gateway...

if not exist "%IB_GATEWAY_PATH%" (
    echo        [SKIP] IB Gateway not found at:
    echo        %IB_GATEWAY_PATH%
    goto skip_ib_gateway
)

:: First check if port is already listening (IB Gateway fully ready)
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        IB Gateway already running and API ready!
    goto ib_gateway_done
)

:: Check if IB Gateway process is running but port not ready
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I /N "ibgateway.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo        IB Gateway process found, waiting for API...
    set QUICK_CHECK=0
    goto quick_port_check
)

:start_ib_fresh
echo        Starting IB Gateway fresh...
start "" "%IB_GATEWAY_PATH%"
echo        Waiting for IB Gateway window (10 seconds)...
timeout /t 10 /nobreak >nul

:: Auto-login with PAPER TRADING account
echo        Auto-login to PAPER account...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 800
    echo WshShell.AppActivate "IB Gateway"
    echo WScript.Sleep 400
    echo If Not WshShell.AppActivate^("IB Gateway"^) Then WshShell.AppActivate "IBKR Gateway"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "%IB_USERNAME%"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "{TAB}"
    echo WScript.Sleep 150
    echo WshShell.SendKeys "%IB_PASSWORD%"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul

:: Wait for IB to process login
echo        Waiting for authentication (10 seconds)...
timeout /t 10 /nobreak >nul

:: Dismiss any warning popups
echo        Dismissing any popups...
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

:quick_port_check
:: Wait for API port to be listening
echo        Waiting for IB Gateway API port %IB_PORT%...
set PORT_ATTEMPTS=0

:port_wait_loop
set /a PORT_ATTEMPTS+=1
if %PORT_ATTEMPTS% GTR 30 (
    echo        [WARNING] IB Gateway port %IB_PORT% not responding after 60 seconds
    echo        Please check IB Gateway manually
    goto ib_gateway_done
)

netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        IB Gateway API ready on port %IB_PORT%!
    goto ib_gateway_done
)

set /a MOD=%PORT_ATTEMPTS% %% 5
if %MOD%==0 (
    echo        Still waiting... (attempt %PORT_ATTEMPTS%/30)
)

timeout /t 2 /nobreak >nul
goto port_wait_loop

:ib_gateway_done
echo        IB Gateway ready!

:skip_ib_gateway
echo.

:: =====================================================
:: STEP 7: START IB DATA PUSHER
:: =====================================================
echo [7/10] Starting IB Data Pusher...

:: Kill existing pusher if running
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%SCRIPTS_DIR%\ib_data_pusher.py" (
    start "IB Data Pusher (Local)" cmd /k "title IB Data Pusher (LOCAL) && color 0C && cd /d %SCRIPTS_DIR% && echo ============================== && echo   IB Data Pusher - LOCAL MODE && echo   Backend: %LOCAL_BACKEND% && echo ============================== && python ib_data_pusher.py --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS%"
    echo        IB Data Pusher started (LOCAL mode)
) else if exist "%DOCUMENTS_DIR%\ib_data_pusher.py" (
    start "IB Data Pusher (Local)" cmd /k "title IB Data Pusher (LOCAL) && color 0C && cd /d %DOCUMENTS_DIR% && echo ============================== && echo   IB Data Pusher - LOCAL MODE && echo   Backend: %LOCAL_BACKEND% && echo ============================== && python ib_data_pusher.py --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS%"
    echo        IB Data Pusher started (LOCAL mode)
) else (
    echo        [WARN] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 8: START OLLAMA HTTP PROXY (for AI features)
:: =====================================================
echo [8/10] Starting Ollama HTTP Proxy...

:: Kill existing proxy if running
taskkill /F /FI "WINDOWTITLE eq Ollama AI Proxy*" >nul 2>&1

if exist "%SCRIPTS_DIR%\ollama_http.py" (
    start "Ollama AI Proxy" cmd /k "title Ollama AI Proxy && color 0D && cd /d %SCRIPTS_DIR% && echo ============================================ && echo   Ollama HTTP Proxy (Local Mode) && echo   Backend: %LOCAL_BACKEND% && echo ============================================ && python ollama_http.py --backend-url %LOCAL_BACKEND%"
    echo        Ollama Proxy started!
) else if exist "%DOCUMENTS_DIR%\ollama_http.py" (
    start "Ollama AI Proxy" cmd /k "title Ollama AI Proxy && color 0D && cd /d %DOCUMENTS_DIR% && echo ============================================ && echo   Ollama HTTP Proxy (Local Mode) && echo   Backend: %LOCAL_BACKEND% && echo ============================================ && python ollama_http.py --backend-url %LOCAL_BACKEND%"
    echo        Ollama Proxy started!
) else (
    echo        [INFO] ollama_http.py not found (AI still works directly)
)
echo.

:: =====================================================
:: STEP 9: WAIT FOR SERVICES
:: =====================================================
echo [9/10] Waiting for services to start...
echo.
echo ============================================
echo    Services Starting...
echo ============================================
echo.
echo    Backend:  %LOCAL_BACKEND%
echo    Frontend: %LOCAL_FRONTEND%
echo    Ollama:   http://localhost:11434
echo    IB Data:  Connected to local backend
echo    GPU:      %GPU_NAME%
echo.
echo    ML Training: Available (GPU accelerated)
echo.
echo    Waiting 20 seconds...
timeout /t 20 /nobreak >nul

:: Open browser
start "" "%LOCAL_FRONTEND%"

:: =====================================================
:: STEP 10: VERIFY AND SHOW STATUS
:: =====================================================
echo.
echo ============================================
echo      TRADECOMMAND LOCAL MODE RUNNING!
echo ============================================
echo.
echo    Frontend: %LOCAL_FRONTEND%
echo    Backend:  %LOCAL_BACKEND%
echo    GPU:      %GPU_NAME%
echo.
echo    Running Services:
echo    * Backend (FastAPI + ML)
echo    * Frontend (React)
echo    * Ollama Server (local AI)
echo    * IB Data Pusher (market data + stops)
echo    * IB Gateway (broker connection)
echo.
echo    Benefits of Local Mode:
echo    * No Cloudflare rate limits
echo    * GPU-accelerated ML training
echo    * Faster AI responses
echo    * Direct IB Gateway connection
echo.
echo    IMPORTANT: Keep all windows open!
echo.
echo ============================================
echo.
echo    Press any key to run health check...
pause >nul

:health_loop
cls
echo.
echo ============================================
echo         TRADECOMMAND HEALTH CHECK
echo ============================================
echo.
echo [Backend]
curl -s %LOCAL_BACKEND%/api/health 2>nul || echo Backend: NOT RESPONDING
echo.
echo.
echo [Ollama]
curl -s http://localhost:11434/api/tags >nul 2>&1 && echo Ollama: Running || echo Ollama: Not running
echo.
echo [IB Gateway]
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1 && echo IB Gateway: Connected on port %IB_PORT% || echo IB Gateway: Not connected
echo.
echo [IB Data Pusher]
curl -s %LOCAL_BACKEND%/api/ib/pushed-data 2>nul | findstr "connected" || echo IB Data: Checking...
echo.
echo [GPU]
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0)}' if torch.cuda.is_available() else 'GPU: Not available')" 2>nul
echo.
echo ============================================
echo Press any key for another check, or close this window
pause >nul
goto health_loop
