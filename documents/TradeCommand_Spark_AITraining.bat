@echo off
title [MAIN] TradeCommand Spark Startup Controller
color 0F

echo.
echo  =====================================================
echo   [MAIN] TradeCommand - DGX Spark AI Trading
echo   Windows PC = IB Gateway + Data Pusher + Collectors
echo   DGX Spark  = Backend + Frontend + MongoDB + AI + GPU
echo  =====================================================
echo.

:: =====================================================
:: CONFIGURATION
:: =====================================================
set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set SCRIPTS_DIR=%REPO_DIR%\documents\scripts

set SPARK_IP=192.168.50.2
set SPARK_USER=spark-1a60
set SPARK_BACKEND=http://%SPARK_IP%:8001
set SPARK_FRONTEND=http://%SPARK_IP%:3000
set SPARK_REPO=~/Trading-and-Analysis-Platform

set IB_GATEWAY_PATH=C:\Jts\ibgateway\1037\ibgateway.exe
set IB_PORT=4002
set IB_SYMBOLS=VIX SPY QQQ IWM DIA XOM CVX CF NTR NVDA AAPL MSFT TSLA AMD

set IB_USERNAME=paperesw100000
set IB_PASSWORD=Socr1025!@!?

:: IB Client IDs (must be unique per connection)
set IB_PUSHER_CLIENT_ID=15
set IB_COLLECTOR_ID_1=16
set IB_COLLECTOR_ID_2=17
set IB_COLLECTOR_ID_3=18
set IB_COLLECTOR_ID_4=19

:: Number of turbo collectors (idle when queue empty, activate from NIA UI)
set NUM_COLLECTORS=4

:: =====================================================
:: STEP 1: CHECK SPARK NETWORK CONNECTION
:: =====================================================
echo [1/8] Checking DGX Spark connectivity...
ping -n 1 -w 2000 %SPARK_IP% >nul 2>&1
if %errorlevel%==0 (
    echo        Spark reachable at %SPARK_IP%
) else (
    echo        [ERROR] Cannot reach Spark at %SPARK_IP%
    echo        Check 10GbE cable and network config
    echo        Windows should be 192.168.50.1, Spark should be 192.168.50.2
    pause
    exit /b 1
)
echo.

:: =====================================================
:: STEP 2: GIT PULL (Both Windows and Spark)
:: =====================================================
echo [2/8] Pulling latest code...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    if %errorlevel%==0 (
        echo        Windows code updated!
    ) else (
        echo        Using local code (Windows)
    )
)
popd

echo        Pulling latest code on Spark...
ssh -n %SPARK_USER%@%SPARK_IP% "cd %SPARK_REPO% && git pull; exit" 2>nul
if %errorlevel%==0 (
    echo        Spark code updated!
) else (
    echo        [WARN] SSH git pull failed - enter password manually or set up SSH keys
)
echo.

:: =====================================================
:: STEP 2.5: STOP EXISTING SPARK SERVICES (clean restart)
:: =====================================================
echo [2.5] Stopping existing Spark services for clean restart...
ssh -n %SPARK_USER%@%SPARK_IP% "pkill -f 'python server.py' 2>/dev/null; pkill -f 'python worker.py' 2>/dev/null; pkill -f 'python3 worker.py' 2>/dev/null; pkill -f 'python3 -m uvicorn' 2>/dev/null; pkill -f 'node.*react-scripts' 2>/dev/null; pkill -f 'yarn start' 2>/dev/null; pkill firefox 2>/dev/null; exit" 2>nul
echo        Kill signals sent. Waiting for clean shutdown (5 sec)...
timeout /t 5 /nobreak >nul
echo        Spark processes stopped.

echo        Shrinking MongoDB cache to 16GB (frees RAM for training)...
ssh -n %SPARK_USER%@%SPARK_IP% "sudo docker exec mongodb mongosh --quiet --eval \"db.adminCommand({setParameter: 1, wiredTigerEngineRuntimeConfig: 'cache_size=16G'})\" 2>/dev/null; exit" 2>nul
echo        MongoDB cache configured.
echo.

:: =====================================================
:: STEP 3: START SPARK SERVICES (fresh)
:: =====================================================
echo [3/8] Starting DGX Spark services (fresh after git pull)...

echo        Starting Spark backend via SSH...
start "" /b ssh -n %SPARK_USER%@%SPARK_IP% "cd %SPARK_REPO%/backend && source ~/venv/bin/activate && nohup python server.py > /tmp/backend.log 2>&1 < /dev/null &"

echo        Waiting for backend startup (30 sec)...
timeout /t 30 /nobreak >nul

set HEALTH_ATTEMPTS=0
:spark_health_loop
set /a HEALTH_ATTEMPTS+=1
if %HEALTH_ATTEMPTS% GTR 15 (
    echo        [WARN] Backend slow - continuing anyway
    goto check_frontend
)
curl -s -f -m 3 %SPARK_BACKEND%/api/health >nul 2>&1
if %errorlevel%==0 (
    echo        Spark backend healthy!
    goto check_frontend
)
echo        Waiting... (%HEALTH_ATTEMPTS%/15)
timeout /t 3 /nobreak >nul
goto spark_health_loop

:check_frontend
echo        Starting Spark frontend via SSH...
start "" /b ssh -n %SPARK_USER%@%SPARK_IP% "cd %SPARK_REPO%/frontend && nohup yarn start > /tmp/frontend.log 2>&1 < /dev/null &"
echo        Frontend starting (compiles in ~20 sec)...

:check_worker
echo        Starting Spark worker via SSH...
start "" /b ssh -n %SPARK_USER%@%SPARK_IP% "cd %SPARK_REPO%/backend && source ~/venv/bin/activate && nohup python worker.py > /tmp/worker.log 2>&1 < /dev/null &"
echo        Worker started
echo.

:: =====================================================
:: STEP 4: IB GATEWAY LOGIN (Windows)
:: =====================================================
echo [4/8] IB Gateway Login (Windows)...

if not exist "%IB_GATEWAY_PATH%" (
    echo        [SKIP] IB Gateway not found at %IB_GATEWAY_PATH%
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
:: STEP 5: START IB DATA PUSHER (Windows -> Spark)
:: =====================================================
echo [5/8] Starting IB Data Pusher (live market data)...

:: Kill existing pusher
taskkill /F /FI "WINDOWTITLE eq [IB PUSHER]*" >nul 2>&1
timeout /t 1 /nobreak >nul

if exist "%SCRIPTS_DIR%\ib_data_pusher.py" (
    start "[IB PUSHER] Market Data" cmd /k "title [IB PUSHER] Market Data Feed to Spark && color 0E && cd /d %SCRIPTS_DIR% && echo. && echo ===================================================== && echo   [IB PUSHER] Real-Time Market Data && echo   Target: DGX Spark (%SPARK_BACKEND%) && echo   Client ID: %IB_PUSHER_CLIENT_ID% ^| Color: YELLOW && echo ===================================================== && echo. && python ib_data_pusher.py --cloud-url %SPARK_BACKEND% --symbols %IB_SYMBOLS% --client-id %IB_PUSHER_CLIENT_ID%"
    echo        Data pusher started (client ID: %IB_PUSHER_CLIENT_ID%)
) else (
    echo        [SKIP] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 6: START TURBO COLLECTORS (idle until NIA triggers)
:: =====================================================
echo [6/8] Starting %NUM_COLLECTORS% Turbo Collectors (idle until collection triggered)...

:: Kill existing collectors
taskkill /F /FI "WINDOWTITLE eq [COLLECTOR*" >nul 2>&1
timeout /t 1 /nobreak >nul

if not exist "%SCRIPTS_DIR%\ib_historical_collector.py" (
    echo        [SKIP] ib_historical_collector.py not found
    goto after_collectors
)

:: Launch collectors with staggered start (2 sec apart)
if %NUM_COLLECTORS% GEQ 1 (
    start /MIN "[COLLECTOR 1] Turbo" cmd /k "title [COLLECTOR 1] Historical Data (Turbo) && color 0C && cd /d %SCRIPTS_DIR% && python ib_historical_collector.py --cloud-url %SPARK_BACKEND% --client-id %IB_COLLECTOR_ID_1% --turbo"
    echo        Collector 1 started (client ID: %IB_COLLECTOR_ID_1%)
    timeout /t 2 /nobreak >nul
)

if %NUM_COLLECTORS% GEQ 2 (
    start /MIN "[COLLECTOR 2] Turbo" cmd /k "title [COLLECTOR 2] Historical Data (Turbo) && color 0C && cd /d %SCRIPTS_DIR% && python ib_historical_collector.py --cloud-url %SPARK_BACKEND% --client-id %IB_COLLECTOR_ID_2% --turbo"
    echo        Collector 2 started (client ID: %IB_COLLECTOR_ID_2%)
    timeout /t 2 /nobreak >nul
)

if %NUM_COLLECTORS% GEQ 3 (
    start /MIN "[COLLECTOR 3] Turbo" cmd /k "title [COLLECTOR 3] Historical Data (Turbo) && color 0C && cd /d %SCRIPTS_DIR% && python ib_historical_collector.py --cloud-url %SPARK_BACKEND% --client-id %IB_COLLECTOR_ID_3% --turbo"
    echo        Collector 3 started (client ID: %IB_COLLECTOR_ID_3%)
    timeout /t 2 /nobreak >nul
)

if %NUM_COLLECTORS% GEQ 4 (
    start /MIN "[COLLECTOR 4] Turbo" cmd /k "title [COLLECTOR 4] Historical Data (Turbo) && color 0C && cd /d %SCRIPTS_DIR% && python ib_historical_collector.py --cloud-url %SPARK_BACKEND% --client-id %IB_COLLECTOR_ID_4% --turbo"
    echo        Collector 4 started (client ID: %IB_COLLECTOR_ID_4%)
)

echo        Collectors idle until you trigger collection from NIA UI
:after_collectors
echo.

:: =====================================================
:: STEP 7: OPEN BROWSER TO SPARK FRONTEND
:: =====================================================
echo [7/8] Opening TradeCommand on Spark...
timeout /t 5 /nobreak >nul
start "" "%SPARK_FRONTEND%"
echo.

:: =====================================================
:: STEP 8: READY
:: =====================================================
echo.
echo ============================================
echo      TRADECOMMAND READY (DGX SPARK)
echo ============================================
echo.
echo    Frontend: %SPARK_FRONTEND%  (DGX Spark)
echo    Backend:  %SPARK_BACKEND%   (DGX Spark)
echo.
echo    +---------------------------------------------------+
echo    ^|  DGX SPARK (192.168.50.2)                         ^|
echo    ^|    Backend API    :8001                            ^|
echo    ^|    Frontend React :3000                            ^|
echo    ^|    MongoDB Docker :27017  (177M+ bars)             ^|
echo    ^|    Ollama AI      :11434                           ^|
echo    ^|    Worker         Background jobs                  ^|
echo    ^|    GPU: Blackwell GB10, 128GB unified memory       ^|
echo    ^|                                                    ^|
echo    ^|  WINDOWS PC (192.168.50.1)                         ^|
echo    ^|    IB Gateway     :%IB_PORT%                            ^|
echo    ^|    IB Pusher      (ID %IB_PUSHER_CLIENT_ID%, live quotes)           ^|
echo    ^|    Collectors x%NUM_COLLECTORS%  (IDs %IB_COLLECTOR_ID_1%-%IB_COLLECTOR_ID_4%, TURBO, idle)  ^|
echo    +---------------------------------------------------+
echo.
echo    +-------------------------------------------------+
echo    ^|  TERMINAL COLOR GUIDE                           ^|
echo    +-------------------------------------------------+
echo    ^|  WHITE       [MAIN]        This controller      ^|
echo    ^|  YELLOW      [IB PUSHER]   Live market data     ^|
echo    ^|  RED x4      [COLLECTOR]   Historical (idle)    ^|
echo    +-------------------------------------------------+
echo.
echo    HOW TO USE:
echo    +-------------------------------------------------+
echo    ^|  TRADING: Just use the UI - everything is live  ^|
echo    ^|                                                  ^|
echo    ^|  COLLECT DATA: Open NIA page, click "Fill Gaps" ^|
echo    ^|    Collectors activate instantly (already running)^|
echo    ^|    ~232 requests/10min with 4 turbo collectors   ^|
echo    ^|    They idle again when queue empties             ^|
echo    ^|                                                  ^|
echo    ^|  TRAIN MODELS: NIA page, click "Train All"      ^|
echo    ^|    Blackwell GPU + 128GB unified memory          ^|
echo    +-------------------------------------------------+
echo.
echo ============================================
echo.
echo Press any key for health check...
pause >nul

:health_check_loop
cls
echo.
echo ============ HEALTH CHECK ============
echo %date% %time%
echo.

:: Spark Backend
curl -s -f -m 3 %SPARK_BACKEND%/api/health >nul 2>&1
if %errorlevel%==0 (
    echo Spark Backend:   ONLINE
) else (
    echo Spark Backend:   OFFLINE
)

:: Spark MongoDB
curl -s -f -m 3 %SPARK_BACKEND%/api/startup-check 2>nul | findstr "\"database\":true" >nul 2>&1
if %errorlevel%==0 (
    echo Spark MongoDB:   CONNECTED
) else (
    echo Spark MongoDB:   CHECKING...
)

:: IB Gateway (Windows)
netstat -an | findstr ":%IB_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo IB Gateway:      CONNECTED (:%IB_PORT%)
) else (
    echo IB Gateway:      DISCONNECTED
)

:: Spark Ollama
curl -s -f -m 3 http://%SPARK_IP%:11434/api/tags >nul 2>&1
if %errorlevel%==0 (
    echo Spark Ollama:    RUNNING
) else (
    echo Spark Ollama:    STOPPED
)

:: Spark Frontend
curl -s -f -m 3 %SPARK_FRONTEND% >nul 2>&1
if %errorlevel%==0 (
    echo Spark Frontend:  RUNNING
) else (
    echo Spark Frontend:  STARTING...
)

:: IB Data Pusher
tasklist /FI "WINDOWTITLE eq [IB PUSHER]*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo IB Pusher:       RUNNING
) else (
    echo IB Pusher:       NOT RUNNING
)

:: Collectors count
set COLLECTOR_COUNT=0
tasklist /FI "WINDOWTITLE eq [COLLECTOR 1]*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" set /a COLLECTOR_COUNT+=1
tasklist /FI "WINDOWTITLE eq [COLLECTOR 2]*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" set /a COLLECTOR_COUNT+=1
tasklist /FI "WINDOWTITLE eq [COLLECTOR 3]*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" set /a COLLECTOR_COUNT+=1
tasklist /FI "WINDOWTITLE eq [COLLECTOR 4]*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" set /a COLLECTOR_COUNT+=1
echo Collectors:      %COLLECTOR_COUNT%/%NUM_COLLECTORS% TURBO (idle until NIA trigger)

:: --------- FOCUS MODE ---------
echo.
echo ------- FOCUS MODE -------
curl -s -f -m 5 %SPARK_BACKEND%/api/focus-mode 2>nul > "%TEMP%\focus_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:,}" %%a in ('findstr "mode" "%TEMP%\focus_check.tmp"') do echo Mode:            %%~a
) else (
    echo Mode:  Unable to check
)
del "%TEMP%\focus_check.tmp" 2>nul

:: --------- COLLECTION QUEUE ---------
echo.
echo ------- DATA COLLECTION -------
curl -s -f -m 5 %SPARK_BACKEND%/api/ib-collector/queue-progress 2>nul > "%TEMP%\queue_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:," %%a in ('findstr "pending" "%TEMP%\queue_check.tmp"') do echo Pending:         %%a
    for /f "tokens=2 delims=:," %%a in ('findstr "claimed" "%TEMP%\queue_check.tmp"') do echo Active:          %%a
    for /f "tokens=2 delims=:," %%a in ('findstr "completed" "%TEMP%\queue_check.tmp"') do echo Completed:       %%a
    for /f "tokens=2 delims=:," %%a in ('findstr "failed" "%TEMP%\queue_check.tmp"') do echo Failed:          %%a
) else (
    echo Queue:  Unable to check
)
del "%TEMP%\queue_check.tmp" 2>nul

:: --------- ML TRAINING ---------
echo.
echo ------- ML TRAINING -------
curl -s -f -m 5 %SPARK_BACKEND%/api/ai-training/status 2>nul > "%TEMP%\train_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:,}" %%a in ('findstr "phase" "%TEMP%\train_check.tmp"') do echo Phase:           %%~a
    for /f "tokens=2 delims=:,}" %%a in ('findstr "status" "%TEMP%\train_check.tmp"') do echo Status:          %%~a
) else (
    echo Training:  Unable to check
)
del "%TEMP%\train_check.tmp" 2>nul

curl -s -f -m 5 %SPARK_BACKEND%/api/ai-modules/timeseries/available-data 2>nul > "%TEMP%\data_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:," %%a in ('findstr "total_bars" "%TEMP%\data_check.tmp"') do echo Training Bars:   %%a
) else (
    echo Training Data: Checking...
)
del "%TEMP%\data_check.tmp" 2>nul

echo.
echo ===================================
echo Press any key to refresh...
echo Press Ctrl+C to exit
pause >nul
goto health_check_loop
