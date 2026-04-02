@echo off
title [MAIN] TradeCommand Startup Controller
color 0F

echo.
echo  =====================================================
echo   [MAIN] TradeCommand - AI Training Startup
echo   This window controls startup - Color: WHITE
echo  =====================================================
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

:: IB Client IDs (must be unique per connection)
set IB_PUSHER_CLIENT_ID=15
set IB_BACKEND_CLIENT_ID=1

set LOCAL_BACKEND=http://localhost:8001
set LOCAL_FRONTEND=http://localhost:3000

:: =====================================================
:: STEP 1: GIT PULL
:: =====================================================
echo [1/9] Pulling latest code...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    if %errorlevel%==0 (
        echo        Code updated!
    ) else (
        echo        Using local code
    )
)
popd
echo.

:: =====================================================
:: STEP 2: CHECK PREREQUISITES
:: =====================================================
echo [2/9] Checking system...
where python >nul 2>&1 && echo        Python: OK || echo        Python: MISSING
where node >nul 2>&1 && echo        Node.js: OK || echo        Node.js: MISSING
where yarn >nul 2>&1 && echo        Yarn: OK || (echo        Installing yarn... && npm install -g yarn >nul 2>&1)

:: Check GPU for ML training
python "%BACKEND_DIR%\scripts\check_gpu.py"

:: Check CNN dependencies (torchvision + PIL)
python -c "import torchvision; from PIL import Image; print('        CNN Models: READY (torchvision + PIL)')" 2>nul || echo        CNN Models: NOT INSTALLED (run InstallML_GPU.bat)

:: Check LightGBM + GPU support (uses lgb.train test — Booster() test is broken on v4.x)
python -c "import lightgbm as lgb; import numpy as np; ds=lgb.Dataset(np.random.rand(20,3).astype(np.float32),label=np.random.randint(0,2,20).astype(np.float32),free_raw_data=False); ds.construct(); lgb.train({'device':'gpu','gpu_platform_id':0,'gpu_device_id':0,'verbose':-1,'objective':'binary','num_leaves':4,'n_iterations':1,'min_data_in_leaf':1,'min_data_in_bin':1,'num_threads':1},ds,num_boost_round=1); print('        LightGBM: GPU ENABLED')" 2>nul
if %errorlevel% neq 0 (
    python -c "import lightgbm; print('        LightGBM: CPU only (GPU not compiled in — run gpu_setup_check.py for instructions)')" 2>nul || echo        LightGBM: MISSING — run: pip install lightgbm
)
echo.

:: =====================================================
:: STEP 3: START OLLAMA FIRST (Backend needs it)
:: =====================================================
echo [3/9] Starting Ollama (AI Backend)...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo        Ollama already running!
    goto ollama_done
)

echo        Starting Ollama server...
start "Ollama Server" /MIN cmd /c "title [OLLAMA] AI Model Server && color 08 && set OLLAMA_HOST=0.0.0.0 && ollama serve"
echo        Waiting for Ollama startup (8 sec)...
timeout /t 8 /nobreak >nul

:: Verify Ollama is ready
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo        Ollama ready!
) else (
    echo        [WARN] Ollama may still be starting...
)

:ollama_done
echo.

:: =====================================================
:: STEP 4: IB GATEWAY LOGIN
:: =====================================================
echo [4/9] IB Gateway Login...

if not exist "%IB_GATEWAY_PATH%" (
    echo        [SKIP] IB Gateway not found
    goto after_ib
)

:: Check if already running and ready
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        Already logged in and ready!
    goto after_ib
)

:: Check if process running but port not ready
tasklist /FI "IMAGENAME eq ibgateway.exe" 2>NUL | find /I /N "ibgateway.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo        IB Gateway running, waiting for API...
    set QUICK_WAIT=0
    goto wait_for_port
)

:: Start fresh
echo        Opening IB Gateway...
start "" "%IB_GATEWAY_PATH%"
timeout /t 6 /nobreak >nul

:: Auto-login
echo        Auto-login to PAPER account...
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 1000
    echo WshShell.AppActivate "IB Gateway"
    echo WScript.Sleep 500
    echo If Not WshShell.AppActivate^("IB Gateway"^) Then WshShell.AppActivate "IBKR Gateway"
    echo WScript.Sleep 400
    echo WshShell.SendKeys "%IB_USERNAME%"
    echo WScript.Sleep 250
    echo WshShell.SendKeys "{TAB}"
    echo WScript.Sleep 200
    echo WshShell.SendKeys "%IB_PASSWORD%"
    echo WScript.Sleep 250
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_login.vbs"
cscript //nologo "%TEMP%\ib_login.vbs"
del "%TEMP%\ib_login.vbs" 2>nul

echo        Waiting for authentication (8 sec)...
timeout /t 8 /nobreak >nul

:: Dismiss popups
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WScript.Sleep 400
    echo WshShell.AppActivate "Warning"
    echo WScript.Sleep 250
    echo WshShell.SendKeys "{ENTER}"
    echo WScript.Sleep 400
    echo WshShell.AppActivate "IBKR"
    echo WScript.Sleep 250
    echo WshShell.SendKeys "{ENTER}"
    echo WScript.Sleep 300
    echo WshShell.SendKeys "{ENTER}"
) > "%TEMP%\ib_popup.vbs"
cscript //nologo "%TEMP%\ib_popup.vbs"
del "%TEMP%\ib_popup.vbs" 2>nul

:wait_for_port
echo        Waiting for API port %IB_PORT%...
set PORT_ATTEMPTS=0

:port_loop
set /a PORT_ATTEMPTS+=1
if %PORT_ATTEMPTS% GTR 20 (
    echo        [WARN] IB Gateway not ready - continue anyway
    goto after_ib
)
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo        IB Gateway API ready!
    goto after_ib
)
set /a MOD=%PORT_ATTEMPTS% %% 5
if %MOD%==0 echo        Still waiting... (%PORT_ATTEMPTS%/20)
timeout /t 2 /nobreak >nul
goto port_loop

:after_ib
echo.

:: =====================================================
:: STEP 5: START BACKEND (NO --reload for stability)
:: =====================================================
echo [5/9] Starting Backend (stable mode)...

:: Kill any existing backend
taskkill /F /FI "WINDOWTITLE eq TradeCommand Backend*" >nul 2>&1
timeout /t 2 /nobreak >nul

:: Start backend WITHOUT --reload (more stable, saves CPU for ML)
start "TradeCommand Backend" cmd /k "title [BACKEND] TradeCommand API Server && color 0A && cd /d %BACKEND_DIR% && echo. && echo ===================================================== && echo   [BACKEND] TradeCommand API Server && echo   Port: 8001 ^| Color: GREEN && echo ===================================================== && echo. && echo Starting backend (stable mode - no auto-reload)... && echo. && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --workers 1"

echo        Backend starting (waiting 20 sec for full init)...
timeout /t 20 /nobreak >nul

:: Health check loop
echo        Checking backend health...
set HEALTH_ATTEMPTS=0

:health_loop
set /a HEALTH_ATTEMPTS+=1
if %HEALTH_ATTEMPTS% GTR 10 (
    echo        [WARN] Backend slow to respond - continuing anyway
    goto backend_done
)

curl -s -f -m 3 %LOCAL_BACKEND%/api/health >nul 2>&1
if %errorlevel%==0 (
    echo        Backend healthy and ready!
    goto backend_done
)
echo        Waiting for backend... (%HEALTH_ATTEMPTS%/10)
timeout /t 3 /nobreak >nul
goto health_loop

:backend_done
echo.

:: =====================================================
:: STEP 6: START FRONTEND
:: =====================================================
echo [6/9] Starting Frontend...

:: Kill existing frontend
taskkill /F /FI "WINDOWTITLE eq TradeCommand Frontend*" >nul 2>&1

:: Write .env file
echo REACT_APP_BACKEND_URL=http://localhost:8001> "%FRONTEND_DIR%\.env"
echo DANGEROUSLY_DISABLE_HOST_CHECK=true>> "%FRONTEND_DIR%\.env"
echo FAST_REFRESH=false>> "%FRONTEND_DIR%\.env"
echo BROWSER=none>> "%FRONTEND_DIR%\.env"

start "TradeCommand Frontend" cmd /k "title [FRONTEND] TradeCommand UI && color 0B && cd /d %FRONTEND_DIR% && echo. && echo ===================================================== && echo   [FRONTEND] TradeCommand React UI && echo   Port: 3000 ^| Color: CYAN && echo ===================================================== && echo. && yarn start"
echo        Frontend starting on port 3000...
echo.

:: =====================================================
:: STEP 7: START IB DATA PUSHER (unique client ID)
:: =====================================================
echo [7/10] Starting IB Data Pusher...

:: Kill existing pusher
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%SCRIPTS_DIR%\ib_data_pusher.py" (
    :: Use unique client ID (15) to avoid conflicts with backend (1)
    start "IB Data Pusher" cmd /k "title [IB PUSHER] Market Data Feed && color 0E && cd /d %SCRIPTS_DIR% && echo. && echo ===================================================== && echo   [IB PUSHER] Real-Time Market Data && echo   Client ID: %IB_PUSHER_CLIENT_ID% ^| Color: YELLOW && echo ===================================================== && echo. && python ib_data_pusher.py --cloud-url %LOCAL_BACKEND% --symbols %IB_SYMBOLS% --client-id %IB_PUSHER_CLIENT_ID%"
    echo        Data pusher started (client ID: %IB_PUSHER_CLIENT_ID%)
) else (
    echo        [SKIP] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 8: START BACKGROUND WORKER (for training/collection)
:: =====================================================
echo [8/9] Starting Background Worker...

:: Kill existing worker
taskkill /F /FI "WINDOWTITLE eq TradeCommand Worker*" >nul 2>&1
timeout /t 1 /nobreak >nul

if exist "%BACKEND_DIR%\worker.py" (
    :: Ensure motor is installed for the worker
    pip install motor --quiet 2>nul
    
    :: Create a helper batch file that loads .env and runs worker
    :: This is needed because env vars from .env must be loaded in the worker's terminal
    (
        echo @echo off
        echo title [WORKER] Background Jobs Processor
        echo color 0D
        echo cd /d %BACKEND_DIR%
        echo echo.
        echo echo =====================================================
        echo echo   [WORKER] Background Jobs Processor
        echo echo   Training, Data Collection, Backtests
        echo echo   Color: PURPLE
        echo echo =====================================================
        echo echo.
        echo echo Loading environment variables...
        echo for /f "usebackq tokens=1,* delims==" %%%%a in ^("%BACKEND_DIR%\.env"^) do set "%%%%a=%%%%b"
        echo echo Waiting for backend to be ready...
        echo timeout /t 10 /nobreak ^>nul
        echo python worker.py
        echo pause
    ) > "%BACKEND_DIR%\run_worker.bat"
    
    start "[WORKER] Background Jobs" cmd /k "title [WORKER] Background Jobs Processor && color 0D && cd /d %BACKEND_DIR% && echo. && echo ===================================================== && echo   [WORKER] Background Jobs Processor && echo   Training, Data Collection, Backtests && echo   Color: PURPLE && echo ===================================================== && echo. && echo Waiting for backend to be ready... && timeout /t 10 /nobreak >nul && python worker.py"
    echo        Worker started (processes training jobs)
) else (
    echo        [SKIP] worker.py not found
)
echo.

:: =====================================================
:: STEP 9: WAIT FOR FRONTEND + OPEN BROWSER
:: =====================================================
echo [9/9] Waiting for frontend to compile...
timeout /t 20 /nobreak >nul
echo.

echo Opening TradeCommand...
start "" "%LOCAL_FRONTEND%"

echo.
echo ============================================
echo      TRADECOMMAND READY!
echo ============================================
echo.
echo    Frontend: %LOCAL_FRONTEND%
echo    Backend:  %LOCAL_BACKEND%
echo.
echo    +-------------------------------------------------+
echo    ^|  TERMINAL COLOR GUIDE                           ^|
echo    +-------------------------------------------------+
echo    ^|  GREEN       [BACKEND]      API Server (8001)   ^|
echo    ^|  CYAN        [FRONTEND]     React UI (3000)     ^|
echo    ^|  YELLOW      [IB PUSHER]    Market Data Feed    ^|
echo    ^|  PURPLE      [WORKER]       Background Jobs     ^|
echo    ^|  GRAY        [OLLAMA]       AI Model Server     ^|
echo    +-------------------------------------------------+
echo.
echo    Focus Mode System (UI-controlled):
echo    +-------------------------------------------------+
echo    ^|  Start Collection:  NIA page or Command Center  ^|
echo    ^|    - Sets COLLECTING mode automatically          ^|
echo    ^|    - Pauses: trading bot, scanner, learning loop ^|
echo    ^|    - Prioritizes: IB data collection             ^|
echo    ^|    - Restores LIVE mode when done                ^|
echo    ^|                                                  ^|
echo    ^|  Start Training:    NIA page "Train All"         ^|
echo    ^|    - Sets TRAINING mode automatically            ^|
echo    ^|    - Pauses: all IB streaming, scanner, bot      ^|
echo    ^|    - GPU + CPU dedicated to model training       ^|
echo    ^|    - Restores LIVE mode when done                ^|
echo    +-------------------------------------------------+
echo.
echo    ML Ready:
echo    * LightGBM with GPU acceleration (auto-detected)
echo    * CNN pipeline (torchvision + PIL)
echo    * Backend in stable mode (no auto-reload)
echo    * Background Worker running for isolated jobs
echo    * Collectors start from UI (not auto-started)
echo.
echo ============================================
echo.
echo Press any key for health check...
pause >nul

:health_check_loop
cls
echo.
echo ============ HEALTH CHECK ============
echo.

:: Backend
curl -s -f -m 3 %LOCAL_BACKEND%/api/health >nul 2>&1
if %errorlevel%==0 (
    echo Backend:     ONLINE
) else (
    echo Backend:     OFFLINE
)

:: IB Gateway
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo IB Gateway:  CONNECTED
) else (
    echo IB Gateway:  DISCONNECTED
)

:: Ollama
curl -s -f -m 3 http://localhost:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo Ollama:      RUNNING
) else (
    echo Ollama:      STOPPED
)

:: Frontend (check if port is in use)
netstat -an | findstr ":3000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo Frontend:    RUNNING
) else (
    echo Frontend:    STARTING...
)

:: Worker (check if window exists)
tasklist /FI "WINDOWTITLE eq TradeCommand Worker*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Worker:      RUNNING
) else (
    echo Worker:      NOT RUNNING
)

:: Focus Mode Status
echo.
echo ------- FOCUS MODE STATUS -------
curl -s -f -m 5 %LOCAL_BACKEND%/api/focus-mode 2>nul > "%TEMP%\focus_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:,}" %%a in ('findstr "mode" "%TEMP%\focus_check.tmp"') do echo Current Mode:  %%~a
) else (
    echo Focus Mode:  Unable to check
)
del "%TEMP%\focus_check.tmp" 2>nul

:: Collection Queue Status
curl -s -f -m 5 %LOCAL_BACKEND%/api/ib-collector/queue-progress 2>nul > "%TEMP%\queue_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:," %%a in ('findstr "pending" "%TEMP%\queue_check.tmp"') do echo Collection Pending:  %%a
    for /f "tokens=2 delims=:," %%a in ('findstr "completed" "%TEMP%\queue_check.tmp"') do echo Collection Done:     %%a
) else (
    echo Collection:  No active jobs
)
del "%TEMP%\queue_check.tmp" 2>nul

:: ML Status
echo.
echo ------- ML TRAINING STATUS -------
python -c "import lightgbm as lgb; p={'device':'gpu','gpu_platform_id':0,'gpu_device_id':0,'verbose':-1}; lgb.Booster(p); print('LightGBM GPU:  ENABLED')" 2>nul || echo LightGBM GPU:  DISABLED (CPU mode)
python -c "import torch; print(f'PyTorch CUDA:  {\"ENABLED (\" + torch.cuda.get_device_name(0) + \")\" if torch.cuda.is_available() else \"DISABLED (CPU)\"}')" 2>nul || echo PyTorch CUDA:  NOT INSTALLED
python -c "import torchvision; print('CNN Pipeline:  READY')" 2>nul || echo CNN Pipeline:  NOT INSTALLED
curl -s -f -m 5 %LOCAL_BACKEND%/api/ai-training/cnn/models 2>nul | findstr "count" >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=2 delims=:," %%a in ('curl -s %LOCAL_BACKEND%/api/ai-training/cnn/models 2^>nul ^| findstr "count"') do (
        echo CNN Models:    %%a trained
    )
) else (
    echo CNN Models:    No models trained yet
)
curl -s -f -m 5 %LOCAL_BACKEND%/api/ai-modules/timeseries/available-data 2>nul | findstr "total_bars" >nul 2>&1
if %errorlevel%==0 (
    echo Training Data: AVAILABLE
    for /f "tokens=2 delims=:" %%a in ('curl -s %LOCAL_BACKEND%/api/ai-modules/timeseries/available-data 2^>nul ^| findstr "total_bars"') do (
        echo Total Bars:    %%a
    )
) else (
    echo Training Data: Checking...
)

echo.
echo ===================================
echo Press any key to check again...
echo Press Ctrl+C to exit
pause >nul
goto health_check_loop
