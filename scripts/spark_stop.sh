#!/bin/bash
# SentCom DGX Spark — Clean Stop
# Kills ALL trading platform processes in correct order + configures MongoDB
# Called by: .bat file (via SSH), or directly on Spark
# Usage: bash scripts/spark_stop.sh

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

# 3. Kill backend + chat server (graceful first, then force)
echo "[3/4] Killing backend + chat server..."
pkill -TERM -f 'python.*server.py' 2>/dev/null && echo "  Sent SIGTERM to server.py" || echo "  No server.py found"
pkill -TERM -f 'python.*chat_server.py' 2>/dev/null && echo "  Sent SIGTERM to chat_server.py" || echo "  No chat_server.py found"
pkill -TERM -f 'uvicorn' 2>/dev/null || true
sleep 3
pkill -9 -f 'python.*server.py' 2>/dev/null || true
pkill -9 -f 'python.*chat_server.py' 2>/dev/null || true
pkill -9 -f 'uvicorn' 2>/dev/null || true

# 4. Kill frontend
echo "[4/4] Killing frontend..."
pkill -f 'node.*react-scripts' 2>/dev/null && echo "  Killed React frontend" || echo "  No frontend found"
pkill -f 'yarn start' 2>/dev/null || true

# Verification
sleep 2
REMAINING=$(pgrep -a python 2>/dev/null | grep -E "(server|worker|training|uvicorn)" || true)
if [ -n "$REMAINING" ]; then
    echo "[WARN] Stubborn processes — force killing..."
    echo "$REMAINING" | awk '{print $1}' | xargs kill -9 2>/dev/null || true
    sleep 1
else
    echo "All processes terminated cleanly."
fi

# v19.30.2 (2026-05-02): final defense-in-depth — kill anything still
# bound to :8001 by port (catches processes whose cmdline didn't match
# `pkill -f 'python.*server.py'` above — e.g., started via full path
# or different python binary). Operator hit "address already in use"
# 2026-05-02 morning because the prior wedged backend's cmdline didn't
# match the pkill pattern.
if command -v fuser >/dev/null 2>&1; then
    if ss -tln 2>/dev/null | grep -q ':8001 '; then
        echo "[CLEANUP] :8001 still bound — killing by port..."
        fuser -k 8001/tcp 2>/dev/null || true
        sleep 1
    fi
    if ss -tln 2>/dev/null | grep -q ':8001 '; then
        echo "[WARN] :8001 STILL bound after fuser — manual intervention needed:"
        echo "       sudo lsof -i :8001"
    else
        echo "Port 8001 free."
    fi
fi

# Configure MongoDB cache (best-effort, no Docker dependency)
echo ""
echo "Configuring MongoDB cache..."
# Try docker exec (with and without sudo), fall back gracefully
(sudo docker exec mongodb mongosh --quiet --eval \
    "db.adminCommand({setParameter: 1, wiredTigerEngineRuntimeConfig: 'cache_size=16G'})" 2>/dev/null \
    || docker exec mongodb mongosh --quiet --eval \
    "db.adminCommand({setParameter: 1, wiredTigerEngineRuntimeConfig: 'cache_size=16G'})" 2>/dev/null) \
    && echo "  MongoDB cache set to 16GB" \
    || echo "  [SKIP] MongoDB cache config (will use defaults)"

echo ""
echo "========================================="
echo "  All services stopped."
echo "========================================="
