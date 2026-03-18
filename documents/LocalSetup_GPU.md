# TradeCommand Local Setup with GPU Optimization

## Your Hardware
- **CPU**: Your processor
- **RAM**: 16GB (8GB typically free)
- **GPU**: NVIDIA GeForce RTX 5060 Ti (~8GB VRAM)

---

## Step 1: Install Prerequisites

Open **PowerShell as Administrator** and run:

```powershell
# Check Python version (need 3.10+)
python --version

# Install yarn globally
npm install -g yarn

# Verify installations
yarn --version
```

---

## Step 2: Install GPU-Enabled ML Libraries

```powershell
# Navigate to your repo
cd C:\Users\13174\Trading-and-Analysis-Platform\backend

# Install CUDA-enabled PyTorch (for RTX 5060 Ti)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Install other ML packages
pip install lightgbm transformers sentence-transformers chromadb

# Verify GPU is detected
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"}')"
```

You should see:
```
CUDA available: True
GPU: NVIDIA GeForce RTX 5060 Ti
```

---

## Step 3: Create Desktop Shortcut

Save this as `StartLocal.bat` on your Desktop:

```batch
@echo off
title TradeCommand - Full Local Mode (GPU)
color 0A

echo ============================================
echo    TradeCommand - FULL LOCAL MODE (GPU)
echo    Backend: localhost:8001
echo    Frontend: localhost:3000
echo    GPU: RTX 5060 Ti Enabled
echo ============================================
echo.

set REPO_DIR=C:\Users\13174\Trading-and-Analysis-Platform
set BACKEND_DIR=%REPO_DIR%\backend
set FRONTEND_DIR=%REPO_DIR%\frontend

:: Start Backend
echo Starting Backend...
start "Local Backend" cmd /k "title Local Backend && cd /d %BACKEND_DIR% && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"

:: Wait for backend
timeout /t 10 /nobreak >nul

:: Start Frontend
echo Starting Frontend...
cd /d %FRONTEND_DIR%
if not exist "node_modules" yarn install
start "Local Frontend" cmd /k "title Local Frontend && cd /d %FRONTEND_DIR% && set REACT_APP_BACKEND_URL=http://localhost:8001 && yarn start"

echo.
echo ============================================
echo    Services Starting...
echo    Backend:  http://localhost:8001
echo    Frontend: http://localhost:3000
echo ============================================
echo.
echo Opening browser in 20 seconds...
timeout /t 20 /nobreak >nul
start http://localhost:3000

pause
```

---

## Step 4: Configure Frontend for Local

Edit `C:\Users\13174\Trading-and-Analysis-Platform\frontend\.env`:

```
REACT_APP_BACKEND_URL=http://localhost:8001
DANGEROUSLY_DISABLE_HOST_CHECK=true
FAST_REFRESH=false
```

---

## Step 5: Run the App

1. **Double-click** `StartLocal.bat` on your Desktop
2. Wait for both terminals to show they're running
3. Browser opens to `http://localhost:3000`

---

## GPU Usage Summary

| Task | Uses GPU? | Memory |
|------|-----------|--------|
| LightGBM Training | CPU (but fast) | ~1GB RAM |
| PyTorch Models | **GPU** | ~2GB VRAM |
| ChromaDB Embeddings | **GPU** | ~1GB VRAM |
| General App | CPU | ~500MB RAM |

---

## Troubleshooting

### "CUDA not available"
```powershell
# Reinstall PyTorch with CUDA
pip uninstall torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

### "yarn not found"
```powershell
npm install -g yarn
```

### "Module not found"
```powershell
cd C:\Users\13174\Trading-and-Analysis-Platform\backend
pip install -r requirements.txt
pip install lightgbm torch transformers sentence-transformers chromadb
```

---

## Running Historical Data Collection

With local running, you can also collect historical data:

1. Open IB Gateway and log in
2. Double-click `StartHistoricalCollector.bat`
3. Data flows: IB Gateway → Local Backend → MongoDB Atlas

---

## Memory Optimization Tips

When training models:
1. Close Chrome and other heavy apps
2. Training uses GPU VRAM (separate from RAM)
3. Your 8GB free RAM is plenty for non-training tasks
