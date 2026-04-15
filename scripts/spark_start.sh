#!/bin/bash
# SentCom DGX Spark — Clean Start
# Kills orphans, then starts backend + frontend
# Usage: bash spark_start.sh [--skip-frontend]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$REPO_DIR/backend"
FRONTEND_DIR="$REPO_DIR/frontend"
SKIP_FRONTEND=false

if [[ "$1" == "--skip-frontend" ]]; then
    SKIP_FRONTEND=true
fi

echo "========================================="
echo "  SentCom — Starting DGX Spark Services"
echo "========================================="

# Step 1: Clean kill any orphans from previous session
echo "[1/5] Cleaning up orphaned processes..."
bash "$SCRIPT_DIR/spark_stop.sh" 2>/dev/null || true
sleep 2
echo ""

# Step 2: Verify MongoDB is running
echo "[2/5] Checking MongoDB..."
if docker ps | grep -q mongodb; then
    echo "  MongoDB container is running"
    # Shrink WiredTiger cache to 16GB (frees RAM for training)
    sudo docker exec mongodb mongosh --quiet --eval \
        "db.adminCommand({setParameter: 1, wiredTigerEngineRuntimeConfig: 'cache_size=16G'})" 2>/dev/null \
        && echo "  MongoDB cache set to 16GB" \
        || echo "  [WARN] Could not configure MongoDB cache"
else
    echo "  [ERROR] MongoDB container not running! Start it with:"
    echo "  sudo docker start mongodb"
    exit 1
fi
echo ""

# Step 3: Activate venv
echo "[3/5] Activating Python environment..."
if [ -f ~/venv/bin/activate ]; then
    source ~/venv/bin/activate
    echo "  Activated ~/venv"
elif [ -f "$REPO_DIR/venv/bin/activate" ]; then
    source "$REPO_DIR/venv/bin/activate"
    echo "  Activated $REPO_DIR/venv"
else
    echo "  [WARN] No venv found, using system Python"
fi
echo ""

# Step 4: Start backend
echo "[4/5] Starting backend server..."
cd "$BACKEND_DIR"
nohup python server.py > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID (log: /tmp/backend.log)"

# Wait for health check
echo "  Waiting for backend to be healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8001/api/health > /dev/null 2>&1; then
        echo "  Backend healthy after ${i}s!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  [WARN] Backend not healthy after 30s — check /tmp/backend.log"
    fi
    sleep 1
done
echo ""

# Step 5: Start frontend (optional)
if [ "$SKIP_FRONTEND" = false ]; then
    echo "[5/5] Starting frontend..."
    cd "$FRONTEND_DIR"
    nohup yarn start > /tmp/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo "  Frontend PID: $FRONTEND_PID (log: /tmp/frontend.log)"
else
    echo "[5/5] Skipping frontend (--skip-frontend)"
fi
echo ""

echo "========================================="
echo "  SentCom — Startup Complete"
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:3000"
echo "  Logs:     tail -f /tmp/backend.log"
echo "========================================="
