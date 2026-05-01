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
# v19.30.2 (2026-05-02): added `.venv/` (Spark's actual path) as the
# first check. Without this the script silently fell through to system
# Python — which has no fastapi installed — and `python server.py`
# would crash with `ModuleNotFoundError: No module named 'fastapi'`,
# leaving the backend down despite the .bat orchestrator reporting
# "Spark services started." Bit the operator 2026-05-02 morning.
echo "[2/5] Activating Python environment..."
if [ -f "$REPO_DIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$REPO_DIR/.venv/bin/activate"
    echo "  Activated $REPO_DIR/.venv"
elif [ -f ~/venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source ~/venv/bin/activate
    echo "  Activated ~/venv"
elif [ -f "$REPO_DIR/venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$REPO_DIR/venv/bin/activate"
    echo "  Activated $REPO_DIR/venv"
else
    echo "  [ERROR] No venv found — backend will likely fail with 'No module named fastapi'"
    echo "          Expected one of: $REPO_DIR/.venv, ~/venv, $REPO_DIR/venv"
fi
# Sanity-check: verify fastapi is reachable BEFORE we launch — fast-fail
# is much better than a backend that launches, crashes, and leaves the
# orchestrator believing it succeeded.
if ! python -c "import fastapi" 2>/dev/null; then
    echo "  [ERROR] 'import fastapi' failed in the active python — bailing."
    echo "          Active python: $(which python)"
    echo "          Run: pip install -r $REPO_DIR/backend/requirements.txt"
    exit 1
fi
echo "  Python ready: $(python --version 2>&1) — fastapi OK"
# Ensure uvloop is installed (2-4x faster event loop)
pip install -q uvloop 2>/dev/null && echo "  uvloop: installed" || echo "  uvloop: skipped"
echo ""

# Step 3: Start backend
echo "[3/5] Starting backend server..."
cd "$BACKEND_DIR"

# v19.30.2 (2026-05-02): defensive port cleanup. spark_stop.sh kills by
# cmdline match (pkill -f), which can miss processes whose cmdline
# differs (full path, python3 vs python, etc.). Add a port-based kill
# so a stale process bound to :8001 can't make the new launch fail
# with "address already in use." Operator hit this 2026-05-02 morning.
if command -v fuser >/dev/null 2>&1; then
    fuser -k 8001/tcp 2>/dev/null && echo "  Killed stale process bound to :8001" || true
    sleep 1
fi
# Wait until the port actually releases (TIME_WAIT can take a few seconds)
for i in $(seq 1 10); do
    if ! ss -tln 2>/dev/null | grep -q ':8001 '; then
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "  [WARN] :8001 still bound after 10s — backend launch may fail"
    fi
    sleep 1
done

nohup python server.py > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

echo "  Waiting for health check..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:8001/api/health > /dev/null 2>&1; then
        echo "  Backend healthy after ${i}s"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "  [WARN] Backend not healthy after 60s — check: tail -f /tmp/backend.log"
    fi
    sleep 1
done

# v19.30.1/.2 (2026-05-02): print the new event-loop + backpressure
# observability tile so the operator can see at a glance whether the
# wedge fixes are healthy on this boot.
if curl -sf http://localhost:8001/api/ib/pusher-health > /tmp/_pusher_health.json 2>/dev/null; then
    echo ""
    python -c "
import json
try:
    h = json.load(open('/tmp/_pusher_health.json')).get('heartbeat', {})
    print('  v19.30.1 backpressure:')
    print(f'    push_in_flight        : {h.get(\"push_in_flight\")}')
    print(f'    push_max_concurrent   : {h.get(\"push_max_concurrent\")}  (cap)')
    print(f'    push_dropped_503_total: {h.get(\"push_dropped_503_total\")}')
    print(f'    pushes_per_min        : {h.get(\"pushes_per_min\")}')
except Exception as e:
    print(f'  (could not parse pusher-health: {e})')
"
    rm -f /tmp/_pusher_health.json
fi
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
