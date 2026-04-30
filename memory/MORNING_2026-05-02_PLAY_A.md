# Morning Play A — Clean Slate Open · 2026-05-02

> Generated 2026-05-01 evening fork. Operator picked Play A: flatten in
> TWS, hard-reset the bot's state, start the day flat, watch v19.29
> verify clean fires.
>
> Don't think during the open. Just follow the steps.

## Why a clean slate

Yesterday's EOD chaos left the bot's `bot_trades` collection desynced
from IB. As of 5:30 PM ET, IB-side reality (TC2000 paper account):

| Symbol | IB pos | Bot tracks | Drift |
|---|---|---|---|
| BP | LONG 4,281 | LONG 1,437 | bot saw 33% of fills |
| CB | LONG 304 | LONG 152 | bot saw 50% of fills |
| HOOD | LONG 473 | LONG 177 | bot saw 37% of fills |
| LITE | LONG 12 | LONG 12 | match ✓ |
| MO/OKLO/SBUX | flat | flat | match ✓ |
| SOFI | LONG 427 | LONG 1,636 + SHORT 301 | catastrophic phantom |
| TMUS | LONG 255 | LONG 255 | match ✓ |

Trailing stops would tick on the wrong share counts. New entries could
collide on duplicate trade-ids. Cleanest recovery: flatten + reset.

NLV $247,235 · BP $506,382 · maint margin $107,922 · excess liquidity
$137,418 — account is healthy, no margin urgency.

---

## ⏰ 8:30 AM ET — Pre-open verification (5 min)

Run on Spark:

```bash
cd ~/Trading-and-Analysis-Platform

# 1. Confirm IB Gateway is up on Windows. From Spark:
curl -s localhost:8001/api/ib/pusher-health | jq
# Look for: any "is_connected" field that is true (or non-null indication)

# 2. Confirm v19.29 hardening is still loaded (defensive sanity)
grep -c "v19.29 WRONG-DIR-SWEEP" backend/services/position_manager.py
# Expect: 1

# 3. Run validation harness baseline
python3 -m backend.scripts.verify_v19_29
# Expect: F=PASS, others NO_DATA / PENDING_RTH (off-hours)

# 4. Confirm the reset script is present + dry-run safe
python3 backend/scripts/reset_bot_open_trades.py --dry-run
# Expect: matched_count=9, no rows modified
```

If step 1 shows pusher disconnected → restart Windows IB Gateway and the
pusher service before continuing. Without the pusher, the bot can't see
fills.

If step 2 returns 0 → v19.29 didn't pull. `git pull` and restart backend
before continuing.

---

## ⏰ 9:20 AM ET — Flatten in TWS

In your TC2000 / IB TWS UI:

1. Switch to the Portfolio / Positions tab.
2. Use the broker's "Close All" or right-click → close on each open row:
   BP, CB, HOOD, LITE, SOFI, TMUS.
3. Wait for fills (should be ~1-3 seconds at the open).
4. Confirm Positions tab shows all rows at 0 / blank.
5. The 5 rows already at 0 (MO, OKLO, SBUX) need no action.

Verify on Spark:

```bash
curl -s localhost:8001/api/portfolio | jq '.positions | map(select(.shares > 0)) | length'
# Expect: 0 (or close to it within a few seconds)

curl -s localhost:8001/api/portfolio | jq '.positions[] | select(.shares > 0) | {symbol, shares, market_value}'
# Expect: empty (no rows)
```

DO NOT proceed to step 9:25 until IB confirms the account is flat.

---

## ⏰ 9:25 AM ET — Hard-reset bot state

This is the destructive step. Two parts:

### Part 1: stop the backend (or it'll hold cached `_open_trades`)

```bash
# Find the running backend PID
pgrep -fa "python.*server.py"

# Kill it cleanly
pkill -f "python.*server.py"

# Wait 2 seconds for shutdown
sleep 2

# Confirm gone
pgrep -fa "python.*server.py" || echo "backend stopped ✓"
```

### Part 2: dry-run the Mongo reset, then commit

```bash
cd ~/Trading-and-Analysis-Platform

# DRY-RUN first — see what would change
.venv/bin/python backend/scripts/reset_bot_open_trades.py --dry-run
# OR if no .venv: pip3 install --user pymongo first, then:
# python3 backend/scripts/reset_bot_open_trades.py --dry-run

# Read the output. Should match the 9 phantoms from yesterday:
#   BP × 3, SOFI × 2, TMUS, LITE, CB, HOOD
# All status=open, all remaining_shares=0.

# If the dry-run output looks right, commit:
.venv/bin/python backend/scripts/reset_bot_open_trades.py --confirm RESET
# Expect: modified_count=9, audit log written

# Sanity check after commit:
.venv/bin/python -c "
from pymongo import MongoClient
db = MongoClient('mongodb://localhost:27017')['tradecommand']
print('open count after reset:', db.bot_trades.count_documents({'status': 'open'}))
print('audit log entries:', db.bot_trades_reset_log.count_documents({}))
"
# Expect: open count after reset: 0
#         audit log entries: 1 (or more if you've reset before)
```

---

## ⏰ 9:27 AM ET — Restart backend

```bash
cd ~/Trading-and-Analysis-Platform
nohup .venv/bin/python backend/server.py > /tmp/backend.log 2>&1 &
# OR if no venv: nohup python3 backend/server.py > /tmp/backend.log 2>&1 &

# Watch the startup banner — must NOT show "degraded mode"
sleep 8
tail -50 /tmp/backend.log | grep -iE "STARTUP|IB Gateway|Trading bot|degraded"
```

What you want to see:
```
IB Gateway: CONNECTED
Trading bot: STARTED in AUTONOMOUS mode
```

What you DON'T want to see:
```
API connection failed: TimeoutError()
IB Gateway: NOT AVAILABLE — IB-dependent services will start in degraded mode
Trading bot: STARTED in AUTONOMOUS mode (paper mode — no IB connection)
```

If you see degraded mode again → bounce IB Gateway on Windows side, then
re-bounce the backend. The auto-connect-at-boot is a known weak point
(planned fix in v19.30 Boot Hygiene Pack).

Verify post-restart state:

```bash
# Bot should report 0 open trades
curl -s localhost:8001/api/trading-bot/status | jq '{running, mode, open_trades}'
# Expect: open_trades: 0, running: true, mode: autonomous

# Sentcom positions should be empty (or just IB-side flat rows)
curl -s localhost:8001/api/sentcom/positions | jq '.positions | length'
# Expect: 0
```

---

## ⏰ 9:30 AM ET — Watch the open

In one terminal, run the live verification harness:

```bash
cd ~/Trading-and-Analysis-Platform
.venv/bin/python -m backend.scripts.verify_v19_29 --watch --watch-interval 30
```

In another terminal, tail the backend log filtered to interesting lines:

```bash
tail -F /tmp/backend.log | grep -iE "TRADE_DROP|intent_already_pending|wrong.dir|phantom|EOD|fill|reject|safety_block"
```

Open IB TWS Orders & Trades window so you can compare what fires.

### What you should observe in the first 10 minutes

1. **F (pipeline health)** stays PASS continuously.
2. **A (intent dedup)** flips PASS the first time the bot tries to
   re-fire a still-pending order intent (should happen within a few
   busy scanner cycles).
3. **B/C/D/E** stay NO_DATA — nothing to sweep, no late-day gates yet.
4. New entries in TWS should have proper bracket orders attached
   (parent + stop + target). No "Unknown order type: bracket" rejections.
5. No 200+ duplicate cancellations like yesterday.

### Red flags

| Symptom | Action |
|---|---|
| TWS shows orders firing but backend log has no fill messages | Pusher pipeline broken — restart pusher on Windows |
| `intent_already_pending` not appearing despite duplicate orders in TWS | Intent dedup wiring broken — paste 5 min of log into chat |
| New trades have remaining_shares=0 right after fill | v19.13 manage stage regression — pause bot, investigate |
| Bot tracks half the IB shares again | Drift bug not fixed — pause bot, escalate |

---

## ⏰ 3:40 PM ET — EOD watch

Keep the verification harness running. Look for:

- **D flips PASS** between 3:45-3:55 PM ET (soft no-new-entries warnings)
- **D continues PASS** after 3:55 PM ET (hard cuts on any late entries)
- **E stays NO_DATA** if every flatten succeeds (the healthy state)
- **E flips PASS** if any close fails (CRITICAL alarm — operator action: TWS manual flatten)

---

## End of day — capture the wins

```bash
# Generate the full report for tonight's tuning conversation
.venv/bin/python -m backend.scripts.verify_v19_29 --json --history-minutes 480 \
  > ~/v19_29_eod_report_$(date +%Y%m%d).json

# Or markdown format for direct paste into chat:
curl -s "localhost:8001/api/diagnostics/export-report?days=1" > ~/diagnostics_eod_$(date +%Y%m%d).md
```

Paste either file back to me and we'll review the day's behaviour, then
pick the next P0 (v19.30 Boot Hygiene Pack vs v19.31 Pre-Aggregated Bars).

---

## Rollback — if something feels wrong

If at any point during the open you want to bail and revert to known-
working state:

```bash
# Stop the bot (status flips running=false; keeps backend alive)
curl -s -X POST localhost:8001/api/trading-bot/stop

# Manual flatten via API (cooldown 120s)
curl -s -X POST "localhost:8001/api/portfolio/flatten-paper?confirm=FLATTEN"

# Or fully bounce the backend
pkill -f "python.*server.py"
```

The reset script's audit log (in `bot_trades_reset_log` collection,
30d TTL) records exactly which trade_ids were flipped at what time, so
the morning state is forensically reconstructable.
