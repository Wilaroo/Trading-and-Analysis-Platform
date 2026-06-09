#!/usr/bin/env python3
"""
SentCom GPU Health Check
========================
Verifies every layer the training pipeline depends on:
  1. nvidia-smi driver state (looks for ERR!)
  2. CUDA_VISIBLE_DEVICES / env
  3. PyTorch CUDA device + a real tensor matmul on GPU
  4. XGBoost GPU training on a tiny dataset (the exact thing that was crashing)
  5. LightGBM GPU availability (informational)
  6. Effective XGB_DEVICE override from backend/.env

Run on the DGX:
    cd /app/backend && python scripts/gpu_healthcheck.py

Exit code 0 = GPU fully healthy, training can use CUDA.
Exit code 1 = GPU NOT usable, must run training on CPU (XGB_DEVICE=cpu).
"""
import os
import subprocess
import sys
import traceback

GREEN = "\033[92m"; RED = "\033[91m"; YEL = "\033[93m"; CYA = "\033[96m"; RST = "\033[0m"

def ok(msg):   print(f"{GREEN}[ OK ]{RST} {msg}")
def fail(msg): print(f"{RED}[FAIL]{RST} {msg}")
def warn(msg): print(f"{YEL}[WARN]{RST} {msg}")
def hdr(msg):  print(f"\n{CYA}=== {msg} ==={RST}")

results = {}


def check_nvidia_smi():
    hdr("1. nvidia-smi driver state")
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20,
        )
        raw = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=20).stdout
        print(raw.strip()[:1200])
        if out.returncode != 0 or "ERR" in (out.stdout + raw):
            fail("nvidia-smi reports an ERR! / non-zero state. GPU is in a driver fault.")
            results["nvidia_smi"] = False
            return
        if not out.stdout.strip():
            fail("nvidia-smi returned no GPU rows.")
            results["nvidia_smi"] = False
            return
        ok(f"Driver reports GPU(s): {out.stdout.strip()}")
        results["nvidia_smi"] = True
    except FileNotFoundError:
        fail("nvidia-smi not found on PATH.")
        results["nvidia_smi"] = False
    except Exception as e:
        fail(f"nvidia-smi failed: {e}")
        results["nvidia_smi"] = False


def check_env():
    hdr("2. CUDA environment variables")
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
    xgb = os.environ.get("XGB_DEVICE")
    print(f"  CUDA_VISIBLE_DEVICES = {cvd!r}")
    print(f"  XGB_DEVICE           = {xgb!r}")
    if cvd in (None, "", "None", "-1"):
        warn("CUDA_VISIBLE_DEVICES is unset/None — GPU may be masked. "
             "If GPU is healthy, leave it unset or '0'.")
    else:
        ok(f"CUDA_VISIBLE_DEVICES set to {cvd!r}")
    results["env_cvd"] = cvd not in ("None", "-1")


def check_torch():
    hdr("3. PyTorch CUDA")
    try:
        import torch
        print(f"  torch {torch.__version__}, built with CUDA {torch.version.cuda}")
        avail = torch.cuda.is_available()
        if not avail:
            fail("torch.cuda.is_available() == False")
            results["torch"] = False
            return
        n = torch.cuda.device_count()
        ok(f"CUDA available, {n} device(s): {[torch.cuda.get_device_name(i) for i in range(n)]}")
        # Real GPU compute test
        a = torch.randn(2048, 2048, device="cuda")
        b = torch.randn(2048, 2048, device="cuda")
        c = (a @ b).sum().item()
        torch.cuda.synchronize()
        ok(f"GPU matmul executed (checksum={c:.2f}). PyTorch CUDA path is LIVE.")
        results["torch"] = True
    except Exception as e:
        fail(f"PyTorch CUDA test failed: {e}")
        traceback.print_exc()
        results["torch"] = False


def check_xgboost():
    hdr("4. XGBoost GPU training (the exact path that was crashing)")
    try:
        import numpy as np
        import xgboost as xgb
        print(f"  xgboost {xgb.__version__}")
        X = np.random.rand(500, 10)
        y = (X[:, 0] + X[:, 1] > 1).astype(int)
        dtrain = xgb.DMatrix(X, label=y)
        # New API uses device='cuda'; this is what raised cudaErrorNoDevice before
        params = {"tree_method": "hist", "device": "cuda", "objective": "binary:logistic"}
        booster = xgb.train(params, dtrain, num_boost_round=5)
        _ = booster.predict(dtrain)
        ok("XGBoost trained on device='cuda' successfully. GPU path is LIVE.")
        results["xgboost"] = True
    except Exception as e:
        fail(f"XGBoost GPU training failed: {e}")
        print(f"{YEL}  -> If GPU is broken, training will fall back to CPU via XGB_DEVICE=cpu.{RST}")
        results["xgboost"] = False


def check_lightgbm():
    hdr("5. LightGBM (informational)")
    try:
        import lightgbm as lgb
        import numpy as np
        X = np.random.rand(500, 10); y = (X[:, 0] > 0.5).astype(int)
        try:
            m = lgb.LGBMClassifier(device="gpu", n_estimators=5)
            m.fit(X, y)
            ok("LightGBM GPU path works.")
            results["lightgbm"] = True
        except Exception:
            warn("LightGBM GPU not available (often CPU-only build). Not a blocker.")
            results["lightgbm"] = None
    except ImportError:
        warn("lightgbm not importable here — skipping.")
        results["lightgbm"] = None


def check_dotenv_override():
    hdr("6. Effective XGB_DEVICE from backend/.env")
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.abspath(env_path)
    val = None
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("XGB_DEVICE"):
                    val = line.split("=", 1)[1].strip()
    print(f"  backend/.env XGB_DEVICE = {val!r}  ({env_path})")
    if val == "cpu":
        warn("XGB_DEVICE=cpu is still set. If the GPU is now healthy, REMOVE this line "
             "(or set to 'cuda') and run ./start_backend.sh --force to use the GPU.")
    elif val in ("cuda", None, ""):
        ok("XGB_DEVICE is not forcing CPU — GPU will be used if available.")


def summary():
    hdr("SUMMARY")
    gpu_live = results.get("nvidia_smi") and results.get("torch") and results.get("xgboost")
    for k in ("nvidia_smi", "torch", "xgboost"):
        v = results.get(k)
        tag = f"{GREEN}PASS{RST}" if v else f"{RED}FAIL{RST}"
        print(f"  {k:12s}: {tag}")
    print()
    if gpu_live:
        print(f"{GREEN}✅ GPU IS HEALTHY.{RST} Remove XGB_DEVICE=cpu from backend/.env "
              f"(if present), then run:  ./start_backend.sh --force")
        return 0
    else:
        print(f"{RED}❌ GPU NOT USABLE.{RST} Keep XGB_DEVICE=cpu in backend/.env and run "
              f"tonight's training on CPU. Reboot/driver-reload again before retrying GPU.")
        return 1


if __name__ == "__main__":
    print(f"{CYA}SentCom GPU Health Check{RST}")
    check_nvidia_smi()
    check_env()
    check_torch()
    check_xgboost()
    check_lightgbm()
    check_dotenv_override()
    sys.exit(summary())
