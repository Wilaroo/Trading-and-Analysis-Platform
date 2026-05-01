# v19.30.1 (2026-05-02) — Event-Loop Wedge Fix + Push-Data Backpressure

> **Operator runbook for the FastAPI wedge fix that landed 2026-05-02.**

## What it fixes

Pre-fix symptom (operator-flagged 2026-05-01):

```
curl -v -m 10 localhost:8001/api/health
*   Trying 127.0.0.1:8001...
* Connected to localhost (127.0.0.1) port 8001
> GET /api/health HTTP/1.1
... 10s pass ...
* Operation timed out after 10000 milliseconds with 0 bytes received
```

The FastAPI backend wedged AFTER `Application startup complete` —
TCP accept worked but no bytes ever returned. ALL endpoints (health,
status, positions) timed out with 0 bytes for the same reason.

## Root cause (3 stacked bugs)

1. **`/api/ib/push-data` was a sync `def` handler** doing sync pymongo
   `update_one` to `ib_live_snapshot` inline. With the Windows pusher
   pushing every ~2s (100+ quotes), this saturated anyio's default
   40-thread pool.

2. **`tick_to_bar_persister.on_push()` ran inline inside that same
   sync handler**, holding a global `threading.Lock` and doing a
   per-bar `update_one` upsert loop. On every minute boundary that's
   ~100 sync mongo writes, all serialised under the lock.

3. **`/api/health` was also sync `def`** so it shared the same anyio
   thread pool. Once the pool saturated, health-check requests queued
   forever and got the 0-byte timeout symptom.

Bonus pre-existing bug found during forensics: the snapshot write
in `/api/ib/push-data` did `from database import get_db` — but the
actual symbol is `get_database`. So the snapshot write had been
silently failing the entire time. Fixed.

## What changed (v19.30.1)

| File | Change | Effect |
|---|---|---|
| `routers/system_router.py` | `/api/health` `def` → `async def` | Health responds even when thread pool saturates |
| `routers/ib.py` | `/api/ib/push-data` `def` → `async def` + `to_thread` for snapshot upsert + `to_thread` for `tick_to_bar.on_push` + 503 backpressure (cap 4 in-flight) | Pushes never block the event loop; pusher gets `Retry-After:5` instead of 120s timeout |
| `routers/ib.py` | `/api/ib/status` + `/api/ib/pushed-data` `def` → `async def` | One less sync handler competing for thread pool |
| `routers/ib.py` | Fixed pre-existing `from database import get_db` typo | Snapshot writes to `ib_live_snapshot` actually work now |
| `routers/agents.py` | `BriefMeAgent` no longer calls now-async `get_pushed_ib_data()` route handler — uses `_pushed_ib_data` dict directly | Avoids async/sync confusion on the same name |

## Spark deploy steps

```bash
# 1. Pull
cd ~/Trading-and-Analysis-Platform
git pull

# 2. Restart backend (SAFE — no schema changes, no env changes)
pkill -f "python server.py"
cd backend && nohup python server.py > /tmp/backend.log 2>&1 &
sleep 8

# 3. Smoke check — should ALL respond instantly now
curl -s -m 5 localhost:8001/api/health
curl -s -m 5 localhost:8001/api/ib/status | jq '.connected'
curl -s -m 5 localhost:8001/api/ib/pusher-health | jq '.heartbeat'

# 4. Now start the Windows pusher and watch:
curl -s localhost:8001/api/ib/pusher-health | \
  jq '.heartbeat | {pushes_per_min, push_in_flight, push_max_concurrent, push_dropped_503_total}'
```

Expected pusher-health heartbeat fields:
- `push_in_flight` — should oscillate 0..3 during normal operation
- `push_max_concurrent` — pinned at 4 (the cap)
- `push_dropped_503_total` — should be 0 in steady state. If it climbs
  fast, the pusher is sending too aggressively or the backend is too
  slow → tune the cap up (`_PUSH_DATA_MAX_CONCURRENT` in `routers/ib.py`)
  or investigate Mongo latency.

## What if the wedge comes back?

A non-zero `push_dropped_503_total` is the new operator signal — when
that climbs and the backend is healthy, the pusher is being throttled
correctly. When the backend goes unhealthy and `push_in_flight` pegs
at 4 forever, that means a thread is hung on a sync mongo call that
got past my offload net.

Diagnostic curl one-liners:

```bash
# Verify push storm doesn't wedge health
( curl -m 5 -X POST localhost:8001/api/ib/push-data \
    -H "Content-Type: application/json" \
    -d '{"timestamp":"2026-05-02T09:30:00+00:00","source":"smoke","quotes":{}}' & 
  curl -m 5 localhost:8001/api/health ) ; wait

# 30 parallel pushes with 5 health checks — pre-fix: all timeouts
# post-fix: most pushes 200, some 503, all health 200 in <50ms
python3 - <<'PY'
import asyncio, aiohttp, time
async def main():
    async with aiohttp.ClientSession() as s:
        async def push(i):
            async with s.post("http://localhost:8001/api/ib/push-data",
                json={"timestamp":"2026-05-02T09:30:00+00:00","source":f"s{i}","quotes":{}}) as r:
                return r.status
        async def health():
            t0 = time.monotonic()
            async with s.get("http://localhost:8001/api/health") as r:
                return r.status, (time.monotonic()-t0)*1000
        results = await asyncio.gather(*[push(i) for i in range(30)] + [health() for _ in range(5)])
        print("pushes:", results[:30])
        print("health:", results[30:])
asyncio.run(main())
PY
```

## Tests

`backend/tests/test_event_loop_wedge_fix_v19_30_1.py` — 7 cases pinning
all three fixes:
- Source-level: `/api/health` is async, `/api/ib/push-data` is async,
  to_thread offload pattern present, 503 backpressure path present.
- Behavioural: 503 short-circuits in <50ms when cap is hit; 8 concurrent
  pushes complete with `<100ms` event-loop block (pre-fix: ~2.5s+).

87/87 combined with v19.23 / v19.24 / v19.26 / v19.27 / v19.29 / v19.30
suites. Ruff clean on new code.
