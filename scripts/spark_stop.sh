#!/bin/bash
# SentCom DGX Spark — Clean Stop
# Kills ALL trading platform processes in correct order
# Usage: bash spark_stop.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "  SentCom — Stopping All Services"
echo "========================================="

# 1. Kill training subprocesses first (heaviest GPU/RAM users)
echo "[1/4] Killing AI training subprocesses..."
pkill -9 -f training_subprocess 2>/dev/null && echo "  Killed training_subprocess" || echo "  No training_subprocess found"
pkill -9 -f training_pipeline 2>/dev/null && echo "  Killed training_pipeline" || echo "  No training_pipeline found"
sleep 1

# 2. Kill worker processes
echo "[2/4] Killing worker processes..."
pkill -f 'python.*worker.py' 2>/dev/null && echo "  Killed worker.py" || echo "  No worker.py found"
pkill -f 'python3.*worker.py' 2>/dev/null || true
sleep 1

# 3. Kill backend server (graceful first, then force)
echo "[3/4] Killing backend server..."
pkill -TERM -f 'python.*server.py' 2>/dev/null && echo "  Sent SIGTERM to server.py" || echo "  No server.py found"
pkill -TERM -f 'uvicorn' 2>/dev/null || true
sleep 3
# Force kill if still alive
pkill -9 -f 'python.*server.py' 2>/dev/null || true
pkill -9 -f 'uvicorn' 2>/dev/null || true

# 4. Kill frontend (optional — takes a while to restart)
echo "[4/4] Killing frontend..."
pkill -f 'node.*react-scripts' 2>/dev/null && echo "  Killed React frontend" || echo "  No frontend found"
pkill -f 'yarn start' 2>/dev/null || true

# Verification
sleep 2
echo ""
echo "Verification — remaining Python processes:"
pgrep -a python | grep -E "(server|worker|training|uvicorn)" || echo "  None (clean)"
echo ""
echo "========================================="
echo "  All services stopped."
echo "========================================="
