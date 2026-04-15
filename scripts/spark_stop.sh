#!/bin/bash
# SentCom DGX Spark — Clean Stop
# Kills ALL trading platform processes in correct order + configures MongoDB
# Called by: .bat file (via SSH), or directly on Spark
# Usage: bash scripts/spark_stop.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================="
echo "  SentCom — Stopping All Services"
echo "========================================="

# 1. Kill training subprocesses first (heaviest GPU/RAM users)
echo "[1/5] Killing AI training subprocesses..."
pkill -9 -f training_subprocess 2>/dev/null && echo "  Killed training_subprocess" || echo "  No training_subprocess found"
pkill -9 -f training_pipeline 2>/dev/null && echo "  Killed training_pipeline" || echo "  No training_pipeline found"
sleep 1

# 2. Kill worker processes
echo "[2/5] Killing worker processes..."
pkill -f 'python.*worker.py' 2>/dev/null && echo "  Killed worker.py" || echo "  No worker.py found"
pkill -f 'python3.*worker.py' 2>/dev/null || true
sleep 1

# 3. Kill backend server (graceful first, then force)
echo "[3/5] Killing backend server..."
pkill -TERM -f 'python.*server.py' 2>/dev/null && echo "  Sent SIGTERM to server.py" || echo "  No server.py found"
pkill -TERM -f 'uvicorn' 2>/dev/null || true
sleep 3
# Force kill if still alive
pkill -9 -f 'python.*server.py' 2>/dev/null || true
pkill -9 -f 'uvicorn' 2>/dev/null || true

# 4. Kill frontend
echo "[4/5] Killing frontend..."
pkill -f 'node.*react-scripts' 2>/dev/null && echo "  Killed React frontend" || echo "  No frontend found"
pkill -f 'yarn start' 2>/dev/null || true

# 5. Verify + stubborn process cleanup
sleep 2
echo "[5/5] Verification pass..."
if pgrep -f training_subprocess > /dev/null 2>&1; then
    echo "  [WARN] Stubborn training process — force killing..."
    pkill -9 -f training_subprocess 2>/dev/null
    sleep 2
fi

REMAINING=$(pgrep -a python 2>/dev/null | grep -E "(server|worker|training|uvicorn)" || true)
if [ -n "$REMAINING" ]; then
    echo "  [WARN] Remaining processes:"
    echo "$REMAINING"
else
    echo "  All processes terminated cleanly."
fi

# 6. Configure MongoDB (shrink cache to free RAM for training/runtime)
echo ""
echo "Configuring MongoDB..."
if docker ps 2>/dev/null | grep -q mongodb; then
    sudo docker exec mongodb mongosh --quiet --eval \
        "db.adminCommand({setParameter: 1, wiredTigerEngineRuntimeConfig: 'cache_size=16G'})" 2>/dev/null \
        && echo "  MongoDB WiredTiger cache set to 16GB" \
        || echo "  [WARN] Could not configure MongoDB cache (non-fatal)"
else
    echo "  [WARN] MongoDB container not running"
fi

echo ""
echo "========================================="
echo "  All services stopped."
echo "========================================="
