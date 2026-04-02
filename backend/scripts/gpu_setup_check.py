"""
GPU Setup Check & LightGBM GPU Installation Helper

Run this script to:
1. Diagnose your GPU + CUDA setup
2. Check if LightGBM has GPU support
3. Get tailored installation instructions for your system

Usage:
    python gpu_setup_check.py           # Full diagnostic
    python gpu_setup_check.py --install # Attempt automatic GPU install
"""

import sys
import os
import platform
import subprocess
import importlib


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check_system():
    section("SYSTEM INFO")
    print(f"  OS:       {platform.system()} {platform.release()}")
    print(f"  Platform: {platform.platform()}")
    print(f"  Python:   {sys.version}")
    print(f"  Arch:     {platform.machine()}")
    return platform.system()


def check_nvidia_gpu():
    section("NVIDIA GPU CHECK")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            for i, line in enumerate(lines):
                parts = [p.strip() for p in line.split(",")]
                print(f"  GPU {i}: {parts[0]}")
                print(f"    Driver:    {parts[1] if len(parts) > 1 else 'unknown'}")
                print(f"    VRAM:      {parts[2] if len(parts) > 2 else 'unknown'}")
                print(f"    Compute:   {parts[3] if len(parts) > 3 else 'unknown'}")
            return True
        else:
            print("  nvidia-smi failed. NVIDIA drivers may not be installed.")
            return False
    except FileNotFoundError:
        print("  nvidia-smi not found. NVIDIA drivers not installed or not on PATH.")
        return False
    except Exception as e:
        print(f"  Error checking GPU: {e}")
        return False


def check_cuda():
    section("CUDA TOOLKIT")
    cuda_path = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME")
    if cuda_path:
        print(f"  CUDA_PATH: {cuda_path}")
    else:
        print("  CUDA_PATH not set in environment")

    try:
        result = subprocess.run(["nvcc", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if "release" in line.lower():
                    print(f"  nvcc: {line.strip()}")
            return True
        else:
            print("  nvcc not found. CUDA toolkit may not be installed.")
            return False
    except FileNotFoundError:
        print("  nvcc not found. CUDA toolkit not installed or not on PATH.")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def check_opencl():
    section("OPENCL (Required for LightGBM GPU)")
    try:
        result = subprocess.run(["clinfo"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            platforms = [l for l in result.stdout.split("\n") if "Platform Name" in l]
            devices = [l for l in result.stdout.split("\n") if "Device Name" in l]
            for p in platforms[:3]:
                print(f"  {p.strip()}")
            for d in devices[:3]:
                print(f"  {d.strip()}")
            return bool(platforms)
        else:
            print("  clinfo not found or failed.")
            return False
    except FileNotFoundError:
        print("  clinfo not installed. Install with: apt install clinfo (Linux) or check CUDA toolkit (Windows)")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def check_lightgbm():
    section("LIGHTGBM STATUS")
    try:
        import lightgbm as lgb
        print(f"  Version: {lgb.__version__}")
    except ImportError:
        print("  LightGBM not installed!")
        return False, False

    # Check GPU support
    import numpy as np
    gpu_works = False
    for device_key in ("device", "device_type"):
        try:
            ds = lgb.Dataset(np.zeros((10, 2)), label=np.zeros(10), free_raw_data=False)
            ds.construct()
            params = {
                device_key: "gpu",
                "gpu_platform_id": 0,
                "gpu_device_id": 0,
                "objective": "binary",
                "num_leaves": 4,
                "n_iterations": 1,
                "verbose": -1,
            }
            b = lgb.train(params, ds, num_boost_round=1)
            gpu_works = True
            print(f"  GPU Support: YES (param: {device_key})")
            del b, ds
            break
        except Exception as e:
            err_str = str(e)[:100]
            continue

    if not gpu_works:
        print(f"  GPU Support: NO")
        print(f"    (pip-installed LightGBM is CPU-only by default)")
    
    return True, gpu_works


def check_torch_cuda():
    section("PYTORCH CUDA (Optional)")
    try:
        import torch
        print(f"  PyTorch:    {torch.__version__}")
        print(f"  CUDA avail: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"  CUDA ver:   {torch.version.cuda}")
            print(f"  GPU name:   {torch.cuda.get_device_name(0)}")
            return True
        return False
    except ImportError:
        print("  PyTorch not installed (optional, not required for LightGBM GPU)")
        return False


def check_conda():
    """Check if conda is available"""
    try:
        result = subprocess.run(["conda", "--version"], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, Exception):
        return False


def print_instructions(os_name, has_gpu, has_cuda, has_opencl, lgbm_installed, lgbm_gpu, has_conda):
    section("INSTALLATION INSTRUCTIONS")

    if lgbm_gpu:
        print("  LightGBM GPU is already working! No action needed.")
        print("  Your training pipeline will automatically use GPU acceleration.")
        return

    if not has_gpu:
        print("  No NVIDIA GPU detected. GPU acceleration requires an NVIDIA GPU.")
        print("  LightGBM will continue using CPU (all cores).")
        return

    print("  Your GPU is detected but LightGBM needs to be reinstalled with GPU support.")
    print()

    # Method 1: conda-forge (easiest)
    if has_conda:
        print("  METHOD 1 (Recommended - Conda):")
        print("  --------------------------------")
        print("  conda install -c conda-forge lightgbm")
        print("  (conda-forge auto-enables GPU since LightGBM v4.4.0)")
        print()

    # Method 2: pip from source
    print(f"  METHOD {'2' if has_conda else '1'} (Build from source via pip):")
    print("  --------------------------------")
    if os_name == "Windows":
        print("  Prerequisites:")
        print("    1. Visual Studio 2019/2022 Build Tools (C++ workload)")
        print("    2. CMake (winget install Kitware.CMake)")
        print("    3. Boost 1.68+:")
        print("       - Download from https://www.boost.org/users/download/")
        print("       - Extract to C:\\boost")
        print("       - Set env: BOOST_ROOT=C:\\boost")
        print("    4. OpenCL SDK (comes with CUDA Toolkit, or download from Khronos)")
        print()
        print("  Install commands:")
        print("    pip uninstall lightgbm -y")
        print("    pip install lightgbm --config-settings=cmake.define.USE_GPU=ON")
        print()
        print("  If that fails, try building from Git:")
        print("    git clone --recursive https://github.com/microsoft/LightGBM")
        print("    cd LightGBM")
        print("    cmake -B build -S . -DUSE_GPU=1 -DBOOST_ROOT=C:\\boost")
        print("    cmake --build build --config Release")
        print("    cd python-package && pip install .")
    else:
        print("  Prerequisites:")
        print("    sudo apt install git cmake build-essential libboost-dev \\")
        print("      libboost-system-dev libboost-filesystem-dev \\")
        print("      nvidia-opencl-dev opencl-headers")
        print()
        print("  Install commands:")
        print("    pip uninstall lightgbm -y")
        print("    pip install lightgbm --config-settings=cmake.define.USE_GPU=ON")
        print()
        print("  Or build from Git:")
        print("    git clone --recursive https://github.com/microsoft/LightGBM")
        print("    cd LightGBM && cmake -B build -S . -DUSE_GPU=1")
        print("    cmake --build build -j$(nproc)")
        print("    cd python-package && pip install .")

    # WSL2 option for Windows
    if os_name == "Windows":
        print()
        print(f"  METHOD {'3' if has_conda else '2'} (WSL2 - Most Reliable on Windows):")
        print("  --------------------------------")
        print("  If native Windows build fails, WSL2 + Ubuntu is the most reliable path:")
        print("    1. wsl --install (installs Ubuntu)")
        print("    2. Install NVIDIA driver 580+ on Windows host")
        print("    3. In WSL: sudo apt install nvidia-opencl-dev opencl-headers")
        print("    4. In WSL: pip install lightgbm --config-settings=cmake.define.USE_GPU=ON")

    print()
    print("  After installation, restart the backend and check logs for:")
    print('    "LightGBM GPU acceleration ENABLED"')
    print()
    print("  Expected speedup: 3-10x faster LightGBM training (histogram building on GPU)")


def attempt_install():
    """Try to automatically install LightGBM with GPU support"""
    section("ATTEMPTING GPU INSTALL")
    
    has_conda = check_conda()
    
    if has_conda:
        print("  Trying conda-forge install...")
        result = subprocess.run(
            ["conda", "install", "-c", "conda-forge", "lightgbm", "-y"],
            capture_output=False, timeout=300
        )
        if result.returncode == 0:
            print("  conda install succeeded! Verifying GPU support...")
            _, gpu = check_lightgbm()
            return gpu
    
    print("  Trying pip install with GPU flag...")
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "lightgbm", "-y"],
                   capture_output=True, timeout=60)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "lightgbm",
         "--config-settings=cmake.define.USE_GPU=ON"],
        capture_output=False, timeout=600
    )
    if result.returncode == 0:
        print("  pip install succeeded! Verifying GPU support...")
        _, gpu = check_lightgbm()
        return gpu
    
    print("  Automatic install failed. Follow the manual instructions above.")
    return False


def main():
    print("\n  LightGBM GPU Setup Diagnostic")
    print("  ─────────────────────────────")

    os_name = check_system()
    has_gpu = check_nvidia_gpu()
    has_cuda = check_cuda()
    has_opencl = check_opencl()
    lgbm_installed, lgbm_gpu = check_lightgbm()
    check_torch_cuda()
    has_conda = check_conda()

    section("SUMMARY")
    print(f"  NVIDIA GPU:      {'YES' if has_gpu else 'NO'}")
    print(f"  CUDA Toolkit:    {'YES' if has_cuda else 'NO'}")
    print(f"  OpenCL:          {'YES' if has_opencl else 'NO'}")
    print(f"  LightGBM:        {'YES' if lgbm_installed else 'NO'}")
    print(f"  LightGBM GPU:    {'YES' if lgbm_gpu else 'NO'}")
    print(f"  Conda available: {'YES' if has_conda else 'NO'}")

    if "--install" in sys.argv:
        attempt_install()
    else:
        print_instructions(os_name, has_gpu, has_cuda, has_opencl, lgbm_installed, lgbm_gpu, has_conda)


if __name__ == "__main__":
    main()
