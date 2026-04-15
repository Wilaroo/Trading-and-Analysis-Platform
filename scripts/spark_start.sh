#!/bin/bash
# SentCom DGX Spark — Clean Start
# Starts backend + worker + frontend (assumes spark_stop.sh already ran)
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

# Step 1: Check MongoDB is reachable (port-based, no Docker dependency)
echo "[1/5] Checking MongoDB..."
if timeout 3 bash -c "echo > /dev/tcp/localhost/27017" 2>/dev/null; then
    echo "  MongoDB accepting connections on port 27017"
else
    echo "  [WARN] MongoDB not responding on port 27017"
    echo "  Attempting to start via Docker..."
    sudo docker start mongodb 2>/dev/null || docker start mongodb 2>/dev/null || true
    sleep 3
    if timeout 3 bash -c "echo > /dev/tcp/localhost/27017" 2>/dev/null; then
        echo "  MongoDB started successfully"
    else
        echo "  [WARN] MongoDB still not responding — backend will retry on its own"
    fi
fi
echo ""

# Step 2: Activate venv
echo "[2/5] Activating Python environment..."
if [ -f ~/venv/bin/activate ]; then
    source ~/venv/bin/activate
    echo "  Activated ~/venv"
elif [ -f "$REPO_DIR/venv/bin/activate" ]; then
    source "$REPO_DIR/venv/bin/activate"
    echo "  Activated $REPO_DIR/venv"
else
    echo "  Using system Python"
fi
echo ""

# Step 3: Start backend
echo "[3/5] Starting backend server..."
cd "$BACKEND_DIR"
nohup python server.py > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

echo "  Waiting for health check..."
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

# Step 4: Start chat server (dedicated LLM process)
echo "[4/6] Starting chat server..."
cd "$BACKEND_DIR"
nohup python chat_server.py > /tmp/chat_server.log 2>&1 &
CHAT_PID=$!
echo "  Chat server PID: $CHAT_PID (port 8002)"
sleep 2
if curl -sf http://localhost:8002/health > /dev/null 2>&1; then
    echo "  Chat server healthy"
else
    echo "  Chat server starting..."
fi
echo ""

# Step 5: Start worker
echo "[5/6] Starting worker..."
cd "$BACKEND_DIR"
nohup python worker.py > /tmp/worker.log 2>&1 &
echo "  Worker PID: $!"
echo ""

# Step 6: Start frontend
if [ "$SKIP_FRONTEND" = false ]; then
    echo "[6/6] Starting frontend..."
    cd "$FRONTEND_DIR"
    nohup yarn start > /tmp/frontend.log 2>&1 &
    echo "  Frontend PID: $! (compiles in ~20s)"
else
    echo "[6/6] Skipping frontend (--skip-frontend)"
fi
echo ""

echo "========================================="
echo "  SentCom — Startup Complete"
echo "  Backend:  http://localhost:8001"
echo "  Chat:     http://localhost:8002"
echo "  Frontend: http://localhost:3000"
echo "========================================="
