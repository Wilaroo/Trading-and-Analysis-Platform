# Tomorrow Pre-Market Checklist — Autopilot Trading Day

A single-page reference for the operator going into a fully automated
trading session on Spark. Built from everything we shipped 2026-04-30
(v19.14 → v19.18). Pin this to a second monitor.

---

## TL;DR — The one command

```bash
~/Trading-and-Analysis-Platform/backend/scripts/morning_check.sh
```

If it prints **AUTOPILOT GREEN** → safe to flip the bot on. If RED or
YELLOW → fix the listed checks before starting. The script's exit code
is `0` / `1` / `2` for green / yellow / red so you can chain it:

```bash
./morning_check.sh && curl -X POST http://localhost:8001/api/trading-bot/start
```

---

## Sequence of events for a fully automated day

### 8:30 AM ET — Pre-market go/no-go (5 min)

1. **Run the morning check**:
   ```bash
   ./scripts/morning_check.sh
   ```
   Expected output: `AUTOPILOT GREEN` with all 5 checks ticked.

2. **If `backfill_data_fresh` is RED**:
   - Click **Collect Data** in the V5 Data Collection panel.
   - Watch the queue drain (usually <2 min for the missing daily bars).
   - Re-run `morning_check.sh` until green.

3. **If `trading_bot_configured` shows EOD time drifted**:
   - Verify `_eod_close_minute` is 55 (the v19.14 default):
     ```bash
     curl -s http://localhost:8001/api/trading-bot/status | jq '{eod_hour, eod_minute, eod_enabled}'
     ```
   - Expected: `{"eod_hour": 15, "eod_minute": 55, "eod_enabled": true}`.

4. **If `open_positions_clean` is RED** — v19.14 EOD failed yesterday:
   - Inspect the stuck positions: `curl -s http://localhost:8001/api/trading-bot/status | jq '.open_trades'`.
   - Manually flatten via the V5 EOD Countdown Banner's **CLOSE ALL NOW**
     button OR `POST /api/trading-bot/eod-close-now`.
   - Then re-run the morning check.

### 9:25 AM ET — Final 5 minutes before bell

- Confirm the V5 HUD shows the v19.14b EOD countdown banner is in `idle`
  state (it's >5 min from the close window so should be hidden).
- Confirm the Buying Power HUD chip shows your expected capital
  (~$250K margin, configurable via `/api/trading-bot/risk-params`).
- Glance at the Scanner card: should show recent activity (cycle count
  ticking up every ~30s).

### 9:30 AM – 3:50 PM ET — Hands off

The bot scans, evaluates, executes, and manages positions autonomously.
v19.15 cycle context cache + v19.16 tier-aware dispatch keep the EVAL
hot path lean even on busy tape (~2,000 alerts/day).

If you want to peek at health mid-session:
```bash
curl -s http://localhost:8001/api/system/morning-readiness | jq .verdict
# → "green" means everything still humming
```

### 3:50 PM ET — EOD pre-warning (5 min before close)

- The V5 EOD Countdown Banner will appear at the top of the Unified
  Stream with a live `MM:SS` countdown.
- Position list shows which intraday symbols are queued for close.
- **CLOSE ALL NOW** button is available if you want to flatten early.

### 3:55 PM ET — Auto-close fires

- v19.14 close-stage runs in parallel via `asyncio.gather`.
- All `close_at_eod=True` (intraday) trades flatten.
- Swing/position trades stay open overnight (correct).
- WS broadcasts `eod_close_started` then `eod_close_completed`.

### 4:00 PM ET — Post-close safety net

- If anything is still locally open, `eod_after_close_alarm` fires and
  the V5 banner flips to deep-red ALARM mode.
- v19.14 P0 #3 retry loop will keep trying every 1-2s until either
  success OR clock crosses 4:00 PM.

### Tomorrow morning — Loop closes

Run `morning_check.sh` again. The `open_positions_clean` check
verifies that yesterday's EOD actually flattened the book. If it goes
red on day N+1, you know day N's EOD didn't complete — triage before
opening bell.

---

## Subsystem reference card

| Pipeline stage | Owner | Verify with |
|---|---|---|
| Data backfill | v19.17 freshness gate | `curl /api/ib-collector/smart-backfill/last \| jq` |
| Symbol universe | `symbol_adv_cache` | `curl /api/backfill/universe?tier=intraday \| jq .count` |
| Scanner | v19.15 + v19.16 | `curl /api/scanner/detector-stats \| jq .last_cycle` |
| Risk + sizing | v19 margin guardrails | `curl /api/trading-bot/risk-params \| jq` |
| Manage stage | v19.13 hardening | `curl /api/trading-bot/status \| jq .open_trades` |
| EOD close | v19.14 + v19.14b | `curl /api/trading-bot/eod-status \| jq` |
| Aggregate verdict | **v19.18** | `./scripts/morning_check.sh` |

---

## When to NOT run autopilot

- `morning_check.sh` exits non-zero → **don't start**.
- IB Gateway showing "PRE-MARKET DATA UNAVAILABLE" → wait until 9:25 AM.
- A pending `pending` count >100 in `historical_data_requests` →
  collector is still working, give it 5 min.
- Multi-Index Regime classifier returning "unknown" → some critical
  ETF (SPY/QQQ/IWM/DIA) lacks fresh data → `morning_check.sh` will
  catch this via `backfill_data_fresh`.

---

## Emergency stop

If something looks wrong mid-session:

```bash
# Hard stop — closes nothing but stops the bot from opening new positions
curl -X POST http://localhost:8001/api/trading-bot/stop

# Hard stop + flatten everything immediately
curl -X POST http://localhost:8001/api/trading-bot/eod-close-now
```

The V5 HUD also has a kill-switch button (red) in the top-right.

---

## Recovery from common Spark hiccups

| Symptom | Fix |
|---|---|
| Backend won't restart | `tail -100 /tmp/backend.log` then `pkill -f "python server.py" && cd backend && nohup python server.py > /tmp/backend.log 2>&1 &` |
| IB Gateway disconnected | Check Windows side: IB Gateway must be on; pusher service must be running on :8765 |
| Scanner stuck | `curl -X POST /api/scanner/reset-cycle` |
| EOD countdown banner stale | Refresh the V5 page — the banner polls every 5s while active, 30s while idle |
| Stuck `claimed` queue requests | `curl -X POST /api/ib-collector/cancel-all-pending` |

---

**Last updated**: 2026-04-30 (v19.18). All systems shipping today are
documented in `/app/memory/CHANGELOG.md`.
