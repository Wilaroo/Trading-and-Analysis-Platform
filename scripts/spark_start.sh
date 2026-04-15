#!/bin/bash
# SentCom DGX Spark — Clean Start
# Kills orphans first, then starts backend + worker + frontend
# Called by: .bat file (via SSH), or directly on Spark
# Usage: bash scripts/spark_start.sh [--skip-frontend]

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
echo "[1/6] Cleaning up orphaned processes..."
bash "$SCRIPT_DIR/spark_stop.sh" 2>/dev/null || true
sleep 2
echo ""

# Step 2: Verify MongoDB is running
echo "[2/6] Checking MongoDB..."
if docker ps 2>/dev/null | grep -q mongodb; then
    echo "  MongoDB container is running"
else
    echo "  [ERROR] MongoDB container not running! Starting..."
    sudo docker start mongodb 2>/dev/null
    sleep 3
    if docker ps 2>/dev/null | grep -q mongodb; then
        echo "  MongoDB started successfully"
    else
        echo "  [FATAL] Cannot start MongoDB. Run: sudo docker start mongodb"
        exit 1
    fi
fi
echo ""

# Step 3: Activate venv
echo "[3/6] Activating Python environment..."
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
echo "[4/6] Starting backend server..."
cd "$BACKEND_DIR"
nohup python server.py > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID (log: /tmp/backend.log)"

# Wait for health check
echo "  Waiting for backend to be healthy..."
for i in $(seq 1 45); do
    if curl -sf http://localhost:8001/api/health > /dev/null 2>&1; then
        echo "  Backend healthy after ${i}s"
        break
    fi
    if [ "$i" -eq 45 ]; then
        echo "  [WARN] Backend not healthy after 45s — check: tail -f /tmp/backend.log"
    fi
    sleep 1
done
echo ""

# Step 5: Start worker
echo "[5/6] Starting worker..."
cd "$BACKEND_DIR"
nohup python worker.py > /tmp/worker.log 2>&1 &
WORKER_PID=$!
echo "  Worker PID: $WORKER_PID (log: /tmp/worker.log)"
echo ""

# Step 6: Start frontend (optional)
if [ "$SKIP_FRONTEND" = false ]; then
    echo "[6/6] Starting frontend..."
    cd "$FRONTEND_DIR"
    nohup yarn start > /tmp/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo "  Frontend PID: $FRONTEND_PID (log: /tmp/frontend.log)"
else
    echo "[6/6] Skipping frontend (--skip-frontend)"
fi
echo ""

echo "========================================="
echo "  SentCom — Startup Complete"
echo "========================================="
echo "  Backend:  http://localhost:8001  (PID $BACKEND_PID)"
echo "  Worker:   Background jobs        (PID $WORKER_PID)"
if [ "$SKIP_FRONTEND" = false ]; then
echo "  Frontend: http://localhost:3000  (PID ${FRONTEND_PID:-N/A})"
fi
echo ""
echo "  Logs:"
echo "    tail -f /tmp/backend.log"
echo "    tail -f /tmp/worker.log"
echo "    tail -f /tmp/frontend.log"
echo "========================================="
