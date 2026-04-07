@echo off
title [MAIN] TradeCommand Spark Startup Controller
color 0F

echo.
echo  =====================================================
echo   [MAIN] TradeCommand - DGX Spark AI Training
echo   Windows PC = IB Gateway + Data Pusher
echo   DGX Spark  = Backend + Frontend + MongoDB + AI
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

set IB_PUSHER_CLIENT_ID=15

:: =====================================================
:: STEP 1: CHECK SPARK NETWORK CONNECTION
:: =====================================================
echo [1/7] Checking DGX Spark connectivity...
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
:: STEP 2: GIT PULL (Windows - for pusher script updates)
:: =====================================================
echo [2/7] Pulling latest code (Windows)...
pushd "%REPO_DIR%"
if exist ".git" (
    git pull origin main 2>nul
    if %errorlevel%==0 (
        echo        Windows code updated!
    ) else (
        echo        Using local code
    )
)
popd
echo.

:: =====================================================
:: STEP 3: START SPARK SERVICES VIA SSH
:: =====================================================
echo [3/7] Starting DGX Spark services...
echo        Pulling latest code on Spark...
ssh %SPARK_USER%@%SPARK_IP% "cd %SPARK_REPO% && git pull" 2>nul
if %errorlevel% neq 0 (
    echo        [WARN] SSH failed - you may need to enter password manually
    echo        Or set up SSH keys: ssh-keygen then ssh-copy-id %SPARK_USER%@%SPARK_IP%
)

echo.
echo        Checking if Spark backend already running...
curl -s -f -m 5 %SPARK_BACKEND%/api/health >nul 2>&1
if %errorlevel%==0 (
    echo        Spark backend already running!
    goto spark_done
)

echo        Starting Spark backend + frontend via SSH...
echo        (You may be prompted for the Spark password)
ssh %SPARK_USER%@%SPARK_IP% "cd %SPARK_REPO%/backend && source ~/venv/bin/activate && nohup python server.py > /tmp/backend.log 2>&1 & cd %SPARK_REPO%/frontend && nohup yarn start > /tmp/frontend.log 2>&1 &"

echo        Waiting for Spark backend startup (30 sec)...
timeout /t 30 /nobreak >nul

:: Health check loop for Spark backend
echo        Checking Spark backend health...
set HEALTH_ATTEMPTS=0

:spark_health_loop
set /a HEALTH_ATTEMPTS+=1
if %HEALTH_ATTEMPTS% GTR 10 (
    echo        [WARN] Spark backend slow to respond - continuing anyway
    goto spark_done
)

curl -s -f -m 3 %SPARK_BACKEND%/api/health >nul 2>&1
if %errorlevel%==0 (
    echo        Spark backend healthy and ready!
    goto spark_done
)
echo        Waiting for Spark backend... (%HEALTH_ATTEMPTS%/10)
timeout /t 3 /nobreak >nul
goto spark_health_loop

:spark_done
echo.

:: =====================================================
:: STEP 4: IB GATEWAY LOGIN (Windows)
:: =====================================================
echo [4/7] IB Gateway Login (Windows)...

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
:: STEP 5: START IB DATA PUSHER (Windows → Spark)
:: =====================================================
echo [5/7] Starting IB Data Pusher (Windows to Spark)...

:: Kill existing pusher
taskkill /F /FI "WINDOWTITLE eq IB Data Pusher*" >nul 2>&1
timeout /t 2 /nobreak >nul

if exist "%SCRIPTS_DIR%\ib_data_pusher.py" (
    start "IB Data Pusher" cmd /k "title [IB PUSHER] Market Data Feed to Spark && color 0E && cd /d %SCRIPTS_DIR% && echo. && echo ===================================================== && echo   [IB PUSHER] Real-Time Market Data && echo   Target: DGX Spark (%SPARK_BACKEND%) && echo   Client ID: %IB_PUSHER_CLIENT_ID% ^| Color: YELLOW && echo ===================================================== && echo. && python ib_data_pusher.py --cloud-url %SPARK_BACKEND% --symbols %IB_SYMBOLS% --client-id %IB_PUSHER_CLIENT_ID%"
    echo        Data pusher started → Spark (%SPARK_BACKEND%)
) else (
    echo        [SKIP] ib_data_pusher.py not found
)
echo.

:: =====================================================
:: STEP 6: OPEN BROWSER TO SPARK FRONTEND
:: =====================================================
echo [6/7] Opening TradeCommand on Spark...
timeout /t 5 /nobreak >nul
start "" "%SPARK_FRONTEND%"
echo.

:: =====================================================
:: STEP 7: READY
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
echo    ^|  ARCHITECTURE                                     ^|
echo    +---------------------------------------------------+
echo    ^|  DGX SPARK (192.168.50.2)                         ^|
echo    ^|    Backend API    :8001                            ^|
echo    ^|    Frontend React :3000                            ^|
echo    ^|    MongoDB Docker :27017                           ^|
echo    ^|    Ollama AI      :11434                           ^|
echo    ^|    GPU: Blackwell GB10, 128GB unified memory       ^|
echo    ^|                                                    ^|
echo    ^|  WINDOWS PC (192.168.50.1)                         ^|
echo    ^|    IB Gateway     :%IB_PORT%                            ^|
echo    ^|    IB Data Pusher (client ID %IB_PUSHER_CLIENT_ID%)              ^|
echo    ^|    Browser UI                                      ^|
echo    +---------------------------------------------------+
echo.
echo    Focus Mode System (UI-controlled):
echo    +---------------------------------------------------+
echo    ^|  Start Collection:  NIA page or Command Center    ^|
echo    ^|    - IB Pusher feeds data from Windows to Spark   ^|
echo    ^|                                                    ^|
echo    ^|  Start Training:    NIA page "Train All"           ^|
echo    ^|    - Blackwell GPU handles all ML training         ^|
echo    ^|    - 128GB unified memory for full dataset         ^|
echo    +---------------------------------------------------+
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
    echo IB Gateway:      CONNECTED (Windows)
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

:: Focus Mode Status
echo.
echo ------- FOCUS MODE STATUS -------
curl -s -f -m 5 %SPARK_BACKEND%/api/focus-mode 2>nul > "%TEMP%\focus_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:,}" %%a in ('findstr "mode" "%TEMP%\focus_check.tmp"') do echo Current Mode:  %%~a
) else (
    echo Focus Mode:  Unable to check
)
del "%TEMP%\focus_check.tmp" 2>nul

:: Collection Queue Status
curl -s -f -m 5 %SPARK_BACKEND%/api/ib-collector/queue-progress 2>nul > "%TEMP%\queue_check.tmp"
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
curl -s -f -m 5 %SPARK_BACKEND%/api/ai-training/status 2>nul > "%TEMP%\train_check.tmp"
if %errorlevel%==0 (
    for /f "tokens=2 delims=:,}" %%a in ('findstr "phase" "%TEMP%\train_check.tmp"') do echo Training Phase:  %%~a
) else (
    echo Training:  Unable to check
)
del "%TEMP%\train_check.tmp" 2>nul

echo.
echo ===================================
echo Press any key to check again...
echo Press Ctrl+C to exit
pause >nul
goto health_check_loop
