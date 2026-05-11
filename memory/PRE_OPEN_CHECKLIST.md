# SentCom Pre-Open Go/No-Go Checklist
**Last updated:** 2026-02-09 · v19.34.66 era
**Time budget:** 25 minutes pre-open

> Run on DGX backend. `export DGX=http://localhost:8001` once at top.

---

## GATE 1 (T-25 → T-20): IB connectivity + Pusher streaming

```bash
curl -s "$DGX/api/ib/orders/open" | python3 -m json.tool | head -20
curl -s "$DGX/api/diagnostic/pusher-rotation-status" | python3 -m json.tool
curl -s "$DGX/api/diagnostic/bar-poll-status" | python3 -m json.tool
```

**PASS:** `/orders/open` returns 200, pusher last-push <10s ago, bar polls <15s ago.
**FAIL → STOP:** Restart Windows IB Gateway + ib_data_pusher.py. Do NOT arm bot.

---

## GATE 2 (T-25 → T-20, parallel): Orphan-GTC + share-drift = ZERO

```bash
curl -s "$DGX/api/safety/orphan-gtc-orders" | python3 -m json.tool
curl -s "$DGX/api/trading-bot/share-drift-status" | python3 -m json.tool
curl -s "$DGX/api/trading-bot/boot-reconcile-status" | python3 -m json.tool
curl -s "$DGX/api/trading-bot/positions/reconcile" | python3 -m json.tool | head -40
```

**PASS:**
- orphan-gtc: `orphan_count: 0` or all `tracked`
- share-drift: `total_drift_shares: 0`
- boot-reconcile: `completed: true`, no `naked_no_position`/`orphan_no_trade`
- positions/reconcile: bot == IB shares per symbol

**FAIL — actions:**
```bash
# auto-cancel orphan GTC
curl -s -X POST "$DGX/api/safety/cancel-orphan-gtc" \
  -H "Content-Type: application/json" -d '{"confirm":"CANCEL-ORPHAN-GTC"}'

# reconcile share-drift
curl -s -X POST "$DGX/api/trading-bot/reconcile-share-drift" \
  -H "Content-Type: application/json" -d '{}'
```
Re-run gate. MUST be zero before open.

---

## GATE 3 (T-20 → T-15): Safety guardrails + daily reset

```bash
curl -s "$DGX/api/safety/status" | python3 -m json.tool
curl -s "$DGX/api/safety/effective-risk-caps" | python3 -m json.tool
curl -s "$DGX/api/risk/circuit-breakers/status" | python3 -m json.tool
curl -s "$DGX/api/risk/health/quick-status" | python3 -m json.tool
```

**PASS:**
- kill_switch_active: true (will be untripped at decision point)
- DLP budget fresh ($2,000 / day, not yesterday's residual)
- circuit breakers `armed: true`, no `tripped`
- health: ok/green

**FAIL:** If DLP not reset → counter-reset bug. Restart backend. **Don't trade today** until investigated.

---

## GATE 4 (T-15 → T-10, parallel with 5): Scanner + pipeline ready

```bash
curl -s "$DGX/api/safety/scanner/status" | python3 -m json.tool
curl -s "$DGX/api/sentcom/status" | python3 -m json.tool
curl -s "$DGX/api/market-state" | python3 -m json.tool
curl -s "$DGX/api/ib/orders/queue/status" | python3 -m json.tool
```

**PASS:**
- scanner `paused: false`, watchlist correct
- sentcom NORMAL, ML audit passing
- market-state regime classified
- order queue `pending: 0`, `in_flight: 0`

**FAIL:**
- Paused scanner: `POST $DGX/api/safety/scanner/resume`
- Stale order queue: investigate before arming

---

## GATE 5 (T-15 → T-10): Regression smoke test

```bash
cd /app/backend && python -m pytest \
  tests/test_v19_34_65_idempotency_and_throttle.py \
  tests/test_v19_34_66_orphan_gtc_reconciler.py \
  tests/test_orphan_reconciler_skips_excess_slice_v19_34_22.py \
  -v --tb=short 2>&1 | tail -30

curl -s "$DGX/api/system/health" | python3 -m json.tool
tail -n 500 /var/log/supervisor/backend.err.log | grep -iE "error|exception|traceback" | tail -20
```

**PASS:** ~44 tests green, system/health ok, no fresh tracebacks.

---

## T-10 → T-5: ARM DECISION

If all gates GREEN:
```bash
curl -s -X POST "$DGX/api/safety/reset-kill-switch" \
  -H "Content-Type: application/json" \
  -d '{"confirm":"RESET-KILL-SWITCH","operator":"<your-handle>"}'

curl -s "$DGX/api/safety/status" | python3 -m json.tool | grep kill_switch
# expected: kill_switch_active: false
```

Any gate red/unclear → **stand down today.**

---

## T-5 → T-0: Visual confirmation

Frontend checks:
1. Top bar: `ALL SYSTEMS · 0 drift · 0 thr · 0 orph`
2. Pusher: `6/min · RPC <50ms`
3. Open positions: EMPTY
4. Scanner: populating
5. EOD ALARM: gone

---

## KNOWN-RISK WATCH (first 30 min of session)

1. **Throttle counter** (v19.34.65) — 60s cooldown might block legit first entries on volatile open
2. **Bracket reissue throttle** (v19.34.65) — 1 per 5min could block needed bracket updates on fast runners
3. **Periodic orphan-GTC reconciler** (v19.34.66) — watch for false-positive `mismatched_size` on legitimate bracket children
4. **Operator-flatten detector NOT YET BUILT** — if you flatten manually via TWS, bot may re-enter. Workaround:
   ```bash
   curl -s -X POST "$DGX/api/safety/scanner/pause" \
     -H "Content-Type: application/json" -d '{"symbols":["TICKER"]}'
   ```
   THEN flatten in TWS.

---

## Quick reference: emergency endpoints

| Action | Endpoint |
|---|---|
| Trip kill switch (panic) | `POST /api/safety/kill-switch/trip` |
| Flatten everything (bot side) | `POST /api/safety/flatten-all` |
| Emergency flatten at IB | `POST /api/safety/emergency-flatten-ib` |
| Pause scanner globally | `POST /api/safety/scanner/pause` |
| Cancel all orphan GTCs | `POST /api/safety/cancel-orphan-gtc` |
| Force share-drift reconcile | `POST /api/trading-bot/reconcile-share-drift` |
