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

echo [3/5] Installing LightGBM...
pip install lightgbm
echo.

echo [4/5] Installing NLP/Embedding libraries...
pip install transformers sentence-transformers
echo.

echo [5/5] Installing ChromaDB (vector database)...
pip install chromadb
echo.

echo ============================================
echo   Verifying GPU Setup...
echo ============================================
python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0)}' if torch.cuda.is_available() else 'No GPU detected')"
echo.

echo ============================================
echo   Testing LightGBM...
echo ============================================
python -c "import lightgbm; print(f'LightGBM version: {lightgbm.__version__}')"
echo.

echo ============================================
echo        SETUP COMPLETE!
echo ============================================
echo.
echo Your RTX 5060 Ti is ready for ML training!
echo.
echo Next steps:
echo 1. Run StartLocal.bat to start the app
echo 2. Go to NIA tab in the app
echo 3. Click "Train All" to train models
echo.
pause
