#!/usr/bin/env bash
# v19.30.1 + v19.30.2 backend launcher for Spark.
# Activates the project venv, kills any stale server, launches in background,
# tails the log briefly, and verifies /api/system/health returns 200.
#
# Usage: ./start_backend.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# 1. Activate venv (Spark uses .venv at repo root)
if [[ -f ".venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif [[ -f "venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
else
    echo "ERROR: no venv found at .venv/ or venv/. Bailing." >&2
    exit 1
fi

# 2. Kill any stale server
pkill -f "python server.py" 2>/dev/null || true
sleep 1

# 3. Launch in background
cd backend
nohup python server.py > /tmp/backend.log 2>&1 &
SERVER_PID=$!
echo "backend started, PID=$SERVER_PID"

# 4. Wait long enough for deferred init to finish (up to 60s on cold boot
# with degraded IB; v19.30.x watchdogs cap each phase at 8-10s).
echo "waiting up to 60s for 'Application startup complete'..."
for i in {1..60}; do
    if grep -q "Application startup complete" /tmp/backend.log 2>/dev/null; then
        echo "  ✓ Application startup complete (after ${i}s)"
        break
    fi
    sleep 1
done

# 5. Verify health
echo ""
echo "=== Last 15 log lines ==="
tail -15 /tmp/backend.log

echo ""
echo "=== Health check ==="
HEALTH=$(curl -s -m 5 http://127.0.0.1:8001/api/system/health || true)
if [[ -n "$HEALTH" ]]; then
    echo "  ✓ /api/system/health: $HEALTH"
else
    echo "  ✗ /api/system/health TIMED OUT — see /tmp/backend.log for the wedge"
    exit 1
fi

echo ""
echo "=== Backpressure observability (v19.30.1) ==="
curl -s -m 5 http://127.0.0.1:8001/api/ib/pusher-health 2>/dev/null | python3 -c "
import sys, json
try:
    h = json.load(sys.stdin).get('heartbeat', {})
    print(f'  push_in_flight        : {h.get(\"push_in_flight\")}')
    print(f'  push_max_concurrent   : {h.get(\"push_max_concurrent\")}')
    print(f'  push_dropped_503_total: {h.get(\"push_dropped_503_total\")}')
    print(f'  pushes_per_min        : {h.get(\"pushes_per_min\")}')
except Exception as e:
    print(f'  (could not parse heartbeat: {e})')
"

echo ""
echo "Backend up. Tail logs with: tail -f /tmp/backend.log"
