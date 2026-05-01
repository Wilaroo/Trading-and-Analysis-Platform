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

# 2. Kill any stale server (by port, not by cmdline — pkill -f misses
# processes whose cmdline doesn't exactly match. v19.30.2 hardening
# after Spark deploy 2026-05-02 hit "address already in use" because
# the old session's PID had a different cmdline.).
echo "killing any process bound to :8001..."
# fuser -k SIGTERMs anything bound to that TCP port — works even when
# cmdline match fails. Fall back to pkill if fuser isn't installed.
if command -v fuser >/dev/null 2>&1; then
    fuser -k 8001/tcp 2>/dev/null || true
else
    pkill -f "python server.py" 2>/dev/null || true
    pkill -f "python3 server.py" 2>/dev/null || true
fi

# Wait for the port to actually be released (TIME_WAIT can take a few
# seconds). Bail with a clear error after 10s instead of letting the
# new server hit "address already in use".
for i in {1..10}; do
    if ! ss -tln 2>/dev/null | grep -q ':8001 '; then
        if [[ $i -gt 1 ]]; then
            echo "  ✓ port 8001 released (after ${i}s)"
        fi
        break
    fi
    if [[ $i -eq 10 ]]; then
        echo "ERROR: port 8001 still bound after 10s. Try:" >&2
        echo "  sudo lsof -i :8001" >&2
        echo "  sudo kill -9 <pid-from-above>" >&2
        exit 1
    fi
    sleep 1
done

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
