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

:: =====================================================
:: STEP 1: CHECK PREREQUISITES
:: =====================================================
echo [1/5] Checking prerequisites...

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
echo.

:: =====================================================
:: STEP 2: START BACKEND
:: =====================================================
echo [2/5] Starting Backend...

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
echo [3/5] Configuring Frontend for local...

:: Create local .env
echo REACT_APP_BACKEND_URL=http://localhost:8001> "%FRONTEND_DIR%\.env"
echo DANGEROUSLY_DISABLE_HOST_CHECK=true>> "%FRONTEND_DIR%\.env"
echo FAST_REFRESH=false>> "%FRONTEND_DIR%\.env"
echo       Frontend configured for localhost
echo.

:: =====================================================
:: STEP 4: START FRONTEND
:: =====================================================
echo [4/5] Starting Frontend...

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
:: STEP 5: WAIT AND OPEN BROWSER
:: =====================================================
echo [5/5] Waiting for services to start...
echo.
echo ============================================
echo    Services Starting...
echo ============================================
echo.
echo    Backend:  http://localhost:8001
echo    Frontend: http://localhost:3000
echo.
echo    ML Training: Available (GPU accelerated)
echo    IB Gateway:  Connect separately if needed
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
echo ============================================
echo         HEALTH CHECK
echo ============================================
echo.
echo Backend Status:
curl -s http://localhost:8001/api/health 2>nul
echo.
echo.
echo GPU Status:
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0)}' if torch.cuda.is_available() else '')" 2>nul
echo.
echo ============================================
echo Press any key for another check, or close this window
pause >nul
goto health_loop
