# Phase 2 — Live Subscription Layer end-to-end smoke test

Run these curls **on the DGX** (where the backend is up) once IB Gateway is
connected (i.e. on a weekday during/around market hours). On weekends the
pusher's `/rpc/subscribe` will return `success: false, error: "ib_disconnected"`
which is expected.

## Quick health
```bash
curl -s http://localhost:8001/api/live/pusher-rpc-health | python3 -m json.tool
```
Expect: `reachable: true, client.enabled: true, client.url: "http://192.168.50.1:8765"`

## Subscribe → list → heartbeat → unsubscribe → list (Phase 2 happy path)
```bash
# 1) Subscribe SPY
curl -s -X POST http://localhost:8001/api/live/subscribe/SPY | python3 -m json.tool

# 2) List active subscriptions — should show SPY ref-count=1
curl -s http://localhost:8001/api/live/subscriptions | python3 -m json.tool

# 3) Renew heartbeat
curl -s -X POST http://localhost:8001/api/live/heartbeat/SPY | python3 -m json.tool

# 4) Subscribe SPY again from another consumer — ref-count goes to 2
curl -s -X POST http://localhost:8001/api/live/subscribe/SPY | python3 -m json.tool

# 5) Unsubscribe once — ref-count drops to 1, pusher NOT called
curl -s -X POST http://localhost:8001/api/live/unsubscribe/SPY | python3 -m json.tool

# 6) Unsubscribe again — ref-count 1→0, pusher /rpc/unsubscribe IS called
curl -s -X POST http://localhost:8001/api/live/unsubscribe/SPY | python3 -m json.tool

# 7) Verify SPY removed from list
curl -s http://localhost:8001/api/live/subscriptions | python3 -m json.tool
```

## Operator sweep (manual stale-sub purge)
```bash
curl -s -X POST http://localhost:8001/api/live/subscriptions/sweep | python3 -m json.tool
```

## Phase 3 snapshot primitives (ready to wire from Briefings/Scanner/Chat)
```bash
# Single symbol
curl -s "http://localhost:8001/api/live/symbol-snapshot/SPY?bar_size=5%20mins" | python3 -m json.tool

# Bulk (max 20)
curl -s -X POST http://localhost:8001/api/live/symbol-snapshots \
  -H "Content-Type: application/json" \
  -d '{"symbols":["SPY","QQQ","IWM"],"bar_size":"5 mins"}' | python3 -m json.tool

# Briefing aggregator (auto-built watchlist: positions + scanner top-10 + indices)
curl -s "http://localhost:8001/api/live/briefing-top-movers?bar_size=5%20mins" | python3 -m json.tool

curl -s "http://localhost:8001/api/live/briefing-watchlist" | python3 -m json.tool
```

## Pass criteria
- All `subscribe` / `heartbeat` / `unsubscribe` calls return `accepted: true` (during market hours)
- Subscriptions list reflects ref-count semantics correctly
- 1→0 transition is the only one that calls pusher `/rpc/unsubscribe` (pusher logs)
- Sweep reports `expired_count` and a list (empty under healthy conditions)
