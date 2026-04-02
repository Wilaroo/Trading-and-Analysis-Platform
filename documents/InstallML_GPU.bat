@echo off
title TradeCommand - Install ML with GPU Support
color 0A

echo ============================================
echo   TradeCommand ML Setup for RTX 5060 Ti
echo ============================================
echo.

:: Get script directory
set SCRIPT_DIR=%~dp0
set REPO_DIR=%SCRIPT_DIR%..
set BACKEND_DIR=%REPO_DIR%\backend

echo [1/5] Checking Python...
python --version
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Install Python 3.10+
    pause
    exit /b 1
)
echo.

echo [2/5] Installing PyTorch with CUDA 12.1 support...
echo       This enables GPU acceleration for your RTX 5060 Ti
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
echo.

echo [3/5] Checking LightGBM GPU support...
echo       Testing if current LightGBM has GPU support...
python -c "import lightgbm as lgb; import numpy as np; ds=lgb.Dataset(np.random.rand(20,3).astype(np.float32),label=np.random.randint(0,2,20).astype(np.float32),free_raw_data=False); ds.construct(); lgb.train({'device':'gpu','gpu_platform_id':0,'gpu_device_id':0,'verbose':-1,'objective':'binary','num_leaves':4,'n_iterations':1,'min_data_in_leaf':1,'min_data_in_bin':1,'num_threads':1},ds,num_boost_round=1); print('       LightGBM GPU already working!')" 2>nul
if %errorlevel%==0 (
    echo       No reinstall needed — GPU support confirmed!
) else (
    echo       GPU not detected in current install. Building from source...
    echo       (This may take a few minutes - compiling from source)
    pip uninstall lightgbm -y >nul 2>&1
    pip install lightgbm --config-settings=cmake.define.USE_GPU=ON
    if %errorlevel% neq 0 (
        echo       [WARN] GPU build failed - installing CPU version as fallback
        pip install lightgbm
        echo       LightGBM installed (CPU only)
    ) else (
        echo       LightGBM installed with GPU support!
    )
)
echo.

echo [4/5] Installing NLP/Embedding libraries...
pip install transformers sentence-transformers
echo.

echo [5/5] Installing CNN + Image Processing libraries...
pip install Pillow mplfinance
echo.

echo ============================================
echo   Verifying GPU Setup...
echo ============================================
python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0)}' if torch.cuda.is_available() else 'No GPU detected')"
echo.

echo ============================================
echo   Testing CNN Pipeline...
echo ============================================
python -c "import torchvision; from PIL import Image; import mplfinance; print('CNN Pipeline: ALL DEPENDENCIES READY')" 2>nul
if %errorlevel% neq 0 (
    echo [WARN] Some CNN dependencies missing. Reinstalling...
    pip install torchvision Pillow mplfinance
)
echo.

echo ============================================
echo   Testing LightGBM GPU...
echo ============================================
python -c "import lightgbm as lgb; p={'device':'gpu','gpu_platform_id':0,'gpu_device_id':0,'verbose':-1}; lgb.Booster(p); print('LightGBM GPU: ENABLED')" 2>nul
if %errorlevel% neq 0 (
    python -c "import lightgbm; print(f'LightGBM version: {lightgbm.__version__} (CPU only)')"
    echo.
    echo       [NOTE] LightGBM GPU not detected. This can happen if:
    echo         - OpenCL runtime is not installed (get from GPU vendor drivers)
    echo         - LightGBM was not compiled with GPU support
    echo         - Try: pip install lightgbm --config-settings=cmake.define.USE_GPU=ON
) else (
    python -c "import lightgbm; print(f'LightGBM version: {lightgbm.__version__} (GPU ENABLED)')"
)
echo.

echo ============================================
echo        SETUP COMPLETE!
echo ============================================
echo.
echo Your RTX 5060 Ti is ready for ML training!
echo.
echo Next steps:
echo 1. Run TradeCommand_AITraining.bat to start the app
echo 2. Go to NIA tab in the app
echo 3. Click "Train All" to train LightGBM models
echo 4. Click "Train CNN" to train chart pattern CNN models
echo 5. CNN models will also auto-train during Weekend Auto batch
echo.
pause
