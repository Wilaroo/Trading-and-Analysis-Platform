# SentCom IB-Direct Migration — Phase L3 Runbook

**Purpose**: Operational checklist to flip `BOT_ORDER_PATH` from `pusher` to `direct` on a live paper account, validate the migration works against real IB Gateway, and unlock the kill switch if and only if the validation passes.

**Pre-condition**: Phase L2 code is on `origin/main` and pulled to DGX. Verify with:
```bash
cd ~/Trading-and-Analysis-Platform && git log --oneline -5 | head
# Top commit should be: 718e1558 v19.34.28 Patch L2b-hotfix1
```

**Account**: Paper `DUN615665` (paperesw100000 alias). Kill switch will start ON.

**Authority to abort**: Operator alone. Any unexpected wedge, drop, error pattern, or "I don't like how this feels" → flip back to pusher immediately. The migration has been waiting this long; another week costs nothing.

---

## ⏱ Time-boxed plan (target: ~75 min including 1-hour post-unlock observation)

| Phase | Window | Action |
|---|---|---|
| 0 | T-30 → T-0 | Pre-flight checks (on pusher) |
| 1 | T-0 → T+5 | Flip env + restart |
| 2 | T+5 → T+25 | Pre-open observation (kill switch ON) |
| 3 | T+25 → T+45 | Market-open observation (kill switch ON) — wait for 3 clean ib-direct placements |
| 4 | T+45 | Decision point: unlock kill switch OR abort |
| 5 | T+45 → T+105 | Post-unlock 1-hour live observation |
| 6 | T+105 | Declare L3 success; ship L4 next |

T-0 = 09:00 ET Monday. Market open = T+30 (09:30 ET).

---

## Phase 0 — Pre-flight checks (T-30 → T-0)

Open three terminals. Terminal A for commands, B for log tail, C for spare.

### 0.1 — Backend healthy on pusher
```bash
# Terminal A
ps -ef | grep "python server.py" | grep -v grep
# Confirm: one process running, started after midnight ET
NEW_PID=$(pgrep -f "python server.py" | head -1)
echo "PID = $NEW_PID, started $(stat -c %y /proc/$NEW_PID 2>/dev/null | cut -d. -f1)"
```
**Pass criteria**: One PID, no zombies. If multiple PIDs, kill all and restart clean before proceeding.

### 0.2 — Verify L2 code is loaded
```bash
cd ~/Trading-and-Analysis-Platform
git log --oneline -5
grep -c "PATCH-L2a\|PATCH-L2b" backend/services/ib_direct_service.py backend/services/trade_executor_service.py backend/services/orphan_gtc_reconciler.py backend/services/position_reconciler.py backend/services/trading_bot_service.py
```
**Pass criteria**: Top commit is `718e1558` (or newer if you've shipped L2 follow-ups). Grep total > 20.

### 0.3 — Migration-status is GREEN on pusher
```bash
curl -s http://localhost:8001/api/system/ib-direct/migration-status | python3 -m json.tool
```
**Pass criteria**:
- `"verdict": "ready"`
- `"order_path": "pusher"`
- `"checks.ib_direct_connected": true`
- `"checks.ib_direct_authorized": true`
- `"checks.watchdog_running": true`
- `"checks.recent_drops_5m": 0`
- `"checks.write_paths_scaffolded": true`
- `"checks.read_paths_wired": true`
- `"recommendations": []`

If ANY check is false or any recommendation appears → **ABORT**. Investigate before flipping.

### 0.4 — Pusher is healthy and pushing data
```bash
curl -s http://localhost:8001/api/ib/pusher-health | python3 -m json.tool
curl -s http://localhost:8001/api/ib/pushed-data | python3 -m json.tool | head -30
```
**Pass criteria**: pusher connected, account_id populated, positions list present (even if empty).

### 0.5 — Account guard healthy
```bash
curl -s http://localhost:8001/api/safety/status | python3 -m json.tool | grep -A 10 "account_guard"
```
**Pass criteria**: `"match": true`, `"current_account_id": "DUN615665"`.

### 0.6 — Kill switch state (should still be tripped from Friday)
```bash
curl -s http://localhost:8001/api/safety/status | python3 -m json.tool | grep -E "kill_switch_active|kill_switch_reason"
```
**Expected**: `kill_switch_active: true`. **Do not reset yet.**

### 0.7 — Account flat
```bash
curl -s http://localhost:8001/api/ib/account/positions | python3 -m json.tool
```
**Pass criteria**: zero open positions. If anything is open, decide whether to flatten manually before proceeding or include those positions in your risk plan.

### 0.8 — Start log tail
```bash
# Terminal B
tail -F /tmp/sentcom.log | grep --line-buffered -E "PATCH-L|WEDGE|IB-DIRECT|kill.switch|naked|orphan|ERROR|TimeoutError|simulated"
```
Leave this running for the duration of L3. Do not close.

✅ **All 8 pre-flight checks pass → proceed to Phase 1. Any fail → ABORT.**

---

## Phase 1 — Flip env + restart (T-0 → T+5)

### 1.1 — Flip the env var
```bash
# Terminal A
cd ~/Trading-and-Analysis-Platform
sed -i 's/^BOT_ORDER_PATH=.*/BOT_ORDER_PATH=direct/' backend/.env
grep BOT_ORDER_PATH backend/.env
# Confirm: BOT_ORDER_PATH=direct
```

### 1.2 — Graceful restart (do NOT kill -9 unless graceful fails)
```bash
OLD_PID=$(pgrep -f "python server.py" | head -1)
echo "Killing old PID = $OLD_PID"
kill $OLD_PID
# Wait up to 15s for graceful shutdown
for i in {1..15}; do
  sleep 1
  if ! kill -0 $OLD_PID 2>/dev/null; then
    echo "Graceful shutdown completed in ${i}s"
    break
  fi
done
# Verify gone, force if needed
if kill -0 $OLD_PID 2>/dev/null; then
  echo "Process still alive after 15s — forcing"
  kill -9 $OLD_PID
  sleep 2
fi
ps -ef | grep "python server.py" | grep -v grep   # should be empty
```

### 1.3 — Relaunch
```bash
cd ~/Trading-and-Analysis-Platform/backend
nohup ~/Trading-and-Analysis-Platform/.venv/bin/python server.py > /tmp/sentcom.log 2>&1 &
NEW_PID=$!
echo "Launched PID = $NEW_PID"
```

### 1.4 — Watch boot for wedges (CRITICAL)
```bash
# Wait 60s, watching Terminal B for WEDGE or ERROR lines
sleep 60
```
**Watch Terminal B during the 60s**:
- ✅ `[STARTUP] v19.34.25 — ib_direct_router registered`
- ✅ `[IB-DIRECT] connected: 192.168.50.1:4002 (clientId=11`
- ✅ `LIVE TRADING MODE — Startup Complete`
- ❌ `=== WEDGE WATCHDOG TRIGGERED ===` → **IMMEDIATE ABORT** (see rollback below)
- ❌ Repeated `TimeoutError` or `ConnectionRefused` → ABORT

A brief wedge (≤30s) during ib-direct's first connect when the old process is still releasing clientId=11 is acceptable — Friday we saw this. A wedge >60s or one located inside `_fetch_ib_positions` is **NOT** acceptable.

### 1.5 — Verify env actually loaded
```bash
NEW_PID=$(pgrep -f "python server.py" | head -1)
strings /proc/$NEW_PID/environ | grep "^BOT_ORDER_PATH"
# Expect: BOT_ORDER_PATH=direct
# NOTE: use `strings`, NOT `cat ... | tr '\0' '\n'` — some terminals
# eat the \0 escape on copy-paste and silently return empty.
```
If this shows `pusher` or empty, the wrong `.env` was edited. Check `backend/.env` (NOT repo root `.env`).

✅ **No wedge + env shows `direct` → proceed to Phase 2. Wedge or env wrong → ABORT.**

---

## Phase 2 — Pre-open observation (T+5 → T+25, kill switch ON)

### 2.1 — Migration-status reflects the flip
```bash
curl -s http://localhost:8001/api/system/ib-direct/migration-status | python3 -m json.tool
```
**Pass criteria**:
- `"order_path": "direct"`  ← **THIS IS THE PROOF**
- `"verdict": "ready"`
- `"checks.recent_drops_5m": 0`
- `"recommendations": []`

If verdict is `degraded` or `blocked`, read the recommendations and act accordingly. Common: socket dropped during restart cleanup — wait 2 min and re-curl. Should self-heal.

### 2.2 — 20-minute soak watch
Re-curl `migration-status` every 5 min through T+25. Watch Terminal B for any errors. Expected log volume: low — scanner is running but kill switch is gating any execution.

**Abort triggers in Phase 2**:
- Any `=== WEDGE WATCHDOG TRIGGERED ===`
- `recent_drops_5m > 0` for more than 5 min
- `ib_direct_connected: false` for more than 1 min
- Any `[v19.34.28 PATCH-L2a]` log line ending in `exception` or `failed`

✅ **20 min clean → proceed to Phase 3.**

---

## Phase 3 — Market-open observation (T+25 → T+45, kill switch ON)

### 3.1 — Market opens at 09:30 ET
Scanner will start finding signals. The kill switch is still ON so the bot **cannot place real orders** — but the executor will log routing decisions. This is the gold-standard test: we see ib-direct routing without actually trading.

### 3.2 — What you're looking for in Terminal B

When a scanner signal hits the executor, you should see:

**Healthy ib-direct routing (good — what we want):**
```
[v19.34.27 PATCH-L1] _ib_bracket: routing via ib_direct (BOT_ORDER_PATH=direct) for <SYMBOL>
[v19.34.27 PATCH-L1] place_bracket_order via ib_direct: <SYMBOL> BUY qty=N ...
```

But because kill switch is on, also expect:
```
kill-switch tripped: Account guard: ... (paper)
```
That's correct — kill switch blocks at the safety gate BEFORE the bracket placement.

**Red flags (abort triggers):**
- Any `[v19.34.27 PATCH-L1] ib_direct.place_bracket_order raised`  
- Any `ib_direct_bracket_exception`  
- Any `SIM-*` order IDs anywhere (means we fell back to simulated, which Patch J should make impossible)  
- Any naked-position-sweep firing aggressively

### 3.3 — Wait for 3 distinct signals
The L3 success criterion is **3 clean ib-direct routing attempts logged** with no errors. Could happen in 30 seconds or 30 minutes depending on scanner sensitivity and market action.

If by T+45 you haven't seen 3 signals, either:
- Market is unusually quiet → extend Phase 3 by 15 min  
- Scanner isn't running → investigate  

**Do NOT unlock kill switch without 3 clean placement attempts logged.**

---

## Phase 4 — Decision point (T+45)

### 4.1 — Final pre-unlock check
```bash
curl -s http://localhost:8001/api/system/ib-direct/migration-status | python3 -m json.tool
```
Verdict must STILL be `ready`. `recent_drops_5m` must be 0. No new recommendations.

### 4.2 — Audit the 3+ placements you observed
Verify in Terminal B's tail that all 3 were:
- Tagged `PATCH-L1` (ib-direct routing, not pusher)
- Refused by kill switch (not by some weird internal error)
- No exceptions thrown anywhere in the routing path

### 4.3 — Decision

**GREEN-LIGHT**: All 3 placements logged cleanly, verdict still `ready`, no wedges, no error spikes. → Proceed to 4.4.

**RED-LIGHT**: Anything questionable. → Rollback (see "ROLLBACK" section). The migration waits another day. **Do not rationalize away red flags.**

### 4.4 — Unlock the kill switch
```bash
# Only execute if 4.3 was GREEN-LIGHT
curl -s -X POST http://localhost:8001/api/safety/reset-kill-switch | python3 -m json.tool
curl -s http://localhost:8001/api/safety/status | python3 -m json.tool | grep -E "kill_switch_active"
# Expect: "kill_switch_active": false
```

Bot is now live on ib-direct.

---

## Phase 5 — Post-unlock 1-hour observation (T+45 → T+105)

### 5.1 — Watch every trade

Terminal B will show the first real trade. You're looking for:

```
[v19.34.27 PATCH-L1] place_bracket_order via ib_direct: <SYMBOL> BUY qty=100 lmt=12.34
  → order_id=12345 status=submitted oca_group=<UUID>
[v19.34.28 PATCH-L2a] attach_oca_stop_target: ... oca=<UUID>
  stop=12346 ($10.00) + target=12347 ($15.00)
```

**Critical**: all three `order_id` values must be **real integers** (4-7 digits), NEVER `SIM-*`. Verify in the UI's "Open Positions" panel or via:
```bash
curl -s http://localhost:8001/api/system/ib-direct/positions | python3 -m json.tool
curl -s http://localhost:8001/api/ib/account/positions | python3 -m json.tool
```
Both should show the same position with the same qty and avg cost.

### 5.2 — Watch for partial-leg failures

The L2a contract: if STP fails → target NOT placed (rejection). If LMT target fails → STP is alive with `partial=true`. If you see `partial=true` in any bracket placement, manually inspect the trade and decide whether to add a target manually or close the position. Don't let a partial sit unattended.

### 5.3 — Watch the migration-status checks
Every 10 min:
```bash
curl -s http://localhost:8001/api/system/ib-direct/migration-status | python3 -m json.tool | grep -E '"verdict"|"recent_drops_5m"|"heartbeat_ok"'
```
Verdict should stay `ready` throughout. Any drift → tighten attention.

### 5.4 — Abort triggers during live operation

Any of these → immediate kill switch trip + rollback:
- ib-direct disconnect that doesn't auto-recover in 60s
- Any `SIM-*` order ID surfacing
- Wedge watchdog fires
- `recent_drops_5m > 2`
- A position appears at IB that the bot doesn't know about (naked sweep would log this)
- A position appears in the bot's `_open_trades` that doesn't exist at IB

To emergency-stop:
```bash
curl -s -X POST http://localhost:8001/api/safety/kill-switch/trip \
  -H 'Content-Type: application/json' \
  -d '{"reason": "L3 abort: <describe what happened>"}'
curl -s -X POST http://localhost:8001/api/safety/flatten-all
```

---

## Phase 6 — Declare success (T+105)

If you reach T+105 with:
- Multiple successful brackets placed via ib-direct
- Every bracket showed real IB integer IDs for parent + stop + target
- No wedges, no `SIM-*`, no naked-position alerts
- Migration-status stayed `ready` throughout
- Kill switch was unlocked at T+45 and has not re-tripped

→ **L3 SUCCESS. IB-Direct migration is operationally live in paper.**

Next: ping me. We'll ship L4 (delete the legacy pusher `queue_order` code paths now that they're proven unused).

---

## ROLLBACK — instant recovery if anything goes wrong

```bash
# 1) Trip kill switch (no new trades)
curl -s -X POST http://localhost:8001/api/safety/kill-switch/trip \
  -H 'Content-Type: application/json' \
  -d '{"reason": "L3 rollback"}'

# 2) Flatten any open positions
curl -s -X POST http://localhost:8001/api/safety/flatten-all

# 3) Revert env
cd ~/Trading-and-Analysis-Platform
sed -i 's/^BOT_ORDER_PATH=.*/BOT_ORDER_PATH=pusher/' backend/.env
grep BOT_ORDER_PATH backend/.env   # confirm pusher

# 4) Restart backend
OLD_PID=$(pgrep -f "python server.py" | head -1)
kill $OLD_PID
sleep 5
kill -0 $OLD_PID 2>/dev/null && kill -9 $OLD_PID
cd ~/Trading-and-Analysis-Platform/backend
nohup ~/Trading-and-Analysis-Platform/.venv/bin/python server.py > /tmp/sentcom.log 2>&1 &
sleep 60

# 5) Verify back to pusher and healthy
curl -s http://localhost:8001/api/system/ib-direct/migration-status | python3 -m json.tool | grep -E '"order_path"|"verdict"'
# Expect: pusher / ready

# 6) Leave kill switch tripped until you've debugged. Send me logs.
```

---

## Appendix A — Useful one-liners

**Pending working orders at IB**:
```bash
curl -s http://localhost:8001/api/system/ib-direct/orders | python3 -m json.tool
```

**Bot's view of open trades vs IB's view of positions** (drift check):
```bash
echo "=== Bot _open_trades ===" && curl -s http://localhost:8001/api/trading-bot/positions | python3 -m json.tool
echo "=== IB positions (authoritative) ===" && curl -s http://localhost:8001/api/system/ib-direct/positions | python3 -m json.tool
```

**Force a fresh positions pull (bypasses ib_async stale cache)**:
```bash
curl -s -X POST http://localhost:8001/api/system/ib-direct/positions | python3 -m json.tool
```

**Recent safety events**:
```bash
curl -s http://localhost:8001/api/safety/status | python3 -m json.tool | python3 -c "import sys,json; d=json.load(sys.stdin); [print(r) for r in d['state']['recent_checks'][-10:]]"
```

---

## Appendix B — Log patterns to grep

| What | Pattern |
|---|---|
| ib-direct routing (good) | `PATCH-L1\|PATCH-L2a` |
| ib-direct fail-hard | `ib_direct_.*_exception\|raised for` |
| Connection events | `IB-DIRECT.*connected\|IB-DIRECT.*reconnected\|IB-DIRECT.*watchdog` |
| Wedges (bad) | `WEDGE WATCHDOG TRIGGERED` |
| Kill switch | `kill.switch tripped\|RESET-KILL-SWITCH` |
| Simulated leak (very bad) | `SIM-\|simulated.*bracket` |
| Naked / orphan alerts | `naked.position\|orphan.gtc\|reconcile` |

`tail -F /tmp/sentcom.log | grep --line-buffered -E '<pattern>'`

---

**End of runbook. Stay calm. Trust the rollback. Don't rationalize red flags.**
