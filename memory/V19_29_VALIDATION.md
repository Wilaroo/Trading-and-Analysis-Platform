# v19.29 RTH Validation Runbook

> Validation harness ships with v19.29 hardening pass. Run on Spark
> before / during the next RTH session to confirm all 5 fixes are
> wired and observable.

## TL;DR — one command

```bash
cd /app && python -m backend.scripts.verify_v19_29
```

That prints a colored summary of all 5 fixes plus a smoke check, with
specific remediation hints next to anything that's not green.

For continuous validation during RTH:

```bash
python -m backend.scripts.verify_v19_29 --watch --watch-interval 30
```

To export the report (paste-into-chat friendly):

```bash
python -m backend.scripts.verify_v19_29 --json > /tmp/verify_v19_29.json
```

## What the 6 checks mean

| Code | Fix | What we look for |
|------|-----|------------------|
| **F** | Pipeline health smoke | `/api/sentcom/positions` HTTP 200 + `/api/trading-bot/status` exposes v19.24 `reconciled_default_*` keys |
| **A** | Order intent dedup | `/api/diagnostic/trade-drops` rows with `reason=intent_already_pending` |
| **B** | Direction-stable reconcile | `/api/sentcom/stream/history` events with kind/text containing `direction_unstable` |
| **C** | Wrong-direction phantom sweep | `/api/sentcom/stream/history` events containing `wrong_direction_phantom` |
| **D** | EOD no-new-entries gate | `/api/sentcom/stream/history` events `eod_no_new_entries_soft` (3:45-3:55pm) + `eod_no_new_entries_hard` (post-3:55pm) |
| **E** | EOD flatten escalation alarm | `/api/sentcom/stream/history` events containing `eod_flatten_failed` |

## Verdict legend

- `PASS` — gate fired in the lookback window. Wiring confirmed.
- `FAIL` — endpoint returned 4xx/5xx OR backend missing v19.24+ defaults.
- `PENDING_RTH` — gate only fires during a specific window (e.g. 3:45-3:55pm); off-hours is expected to be empty.
- `NO_DATA` — endpoint healthy but gate hasn't fired in the lookback. Could be healthy (no triggering event) OR silently broken.
- `ERROR` — connection / parsing error reaching the endpoint.

## Manual one-liners (no script)

If you don't have Python available on a remote terminal, the same
queries via curl:

```bash
# F. Pipeline health
curl -s http://localhost:8001/api/sentcom/positions | jq '.success, (.positions | length)'
curl -s http://localhost:8001/api/trading-bot/status | jq '.risk_params.reconciled_default_stop_pct, .risk_params.reconciled_default_rr'

# A. Intent dedup blocks (last 4h)
curl -s "http://localhost:8001/api/diagnostic/trade-drops?minutes=240&limit=200" \
  | jq '.recent[] | select(.reason | test("intent_already_pending"))'

# B. Direction stability
curl -s "http://localhost:8001/api/sentcom/stream/history?minutes=1440&q=direction_unstable&limit=20" \
  | jq '.messages[] | {symbol, content: .content[0:80], at: .timestamp}'

# C. Phantom sweep
curl -s "http://localhost:8001/api/sentcom/stream/history?minutes=1440&q=wrong_direction_phantom&limit=20" \
  | jq '.messages[] | {symbol, content: .content[0:80], at: .timestamp}'

# D. EOD no-new-entries
curl -s "http://localhost:8001/api/sentcom/stream/history?minutes=480&q=eod_no_new_entries&limit=20" \
  | jq '.messages[] | {symbol, content: .content[0:80], at: .timestamp}'

# E. EOD flatten alarm
curl -s "http://localhost:8001/api/sentcom/stream/history?minutes=1440&q=eod_flatten_failed&limit=20" \
  | jq '.messages[] | {symbol, content: .content[0:80], at: .timestamp}'
```

## Active probe (use with care)

For check **B**, the gate only fires if you actively call the
reconcile endpoint while the IB direction is in flux. You can force
it to trip on a real symbol:

```bash
python -m backend.scripts.verify_v19_29 --probe-reconcile SBUX
```

This **POSTs** to `/api/trading-bot/reconcile` with `{"symbols":
["SBUX"]}`. If the symbol is currently a stable IB orphan, it gets
materialized into `bot_trades`. If the direction is unstable
(<30s observation history), it gets skipped with
`direction_unstable`. Either outcome demonstrates the gate is wired.

⚠️ Do NOT use `--probe-reconcile` on a symbol that's actively moving
or that you don't want claimed; this is a real side-effect call.

## Operator post-pull workflow

Run in this order on the Spark after `git pull` + restart:

1. **Smoke before RTH (any time)**
   ```bash
   python -m backend.scripts.verify_v19_29
   ```
   Expect: F=PASS, all others NO_DATA or PENDING_RTH (off-hours).
   If F=FAIL → backend didn't pick up v19.24+ defaults; check
   `bot_state.risk_params` in Mongo.

2. **Verify SOFI catastrophe is gone**
   ```bash
   curl -s http://localhost:8001/api/sentcom/positions \
     | jq '.positions[] | select(.symbol=="SOFI") | {direction, source, shares, status}'
   ```
   The pre-v19.29 phantom (SOFI SHORT 2014sh) should have been
   auto-swept on first manage tick post-pull. The position list
   should either show no SOFI row or only the IB-side row.

3. **Watch during opening 30 min of RTH**
   ```bash
   python -m backend.scripts.verify_v19_29 --watch --watch-interval 30
   ```
   You're looking for:
   - **A** to flip from NO_DATA to PASS once the bot tries a duplicate
     order intent (most likely to happen at peak scanner cycles).
   - **F** stays PASS continuously.

4. **Watch during 3:40-3:55 PM ET**
   - **D** must flip to PASS — soft warnings 3:45-3:55pm, hard cuts
     after 3:55pm.

5. **Watch 3:55-4:00 PM ET**
   - **E** stays NO_DATA if every flatten succeeds (the healthy
     state). If any close fails, E flips to PASS to confirm the
     CRITICAL alarm fired in the unified stream so you saw it
     in real-time on V5.

## What "operator-side feedback to reshape the spec" means

Once you've done the validation pass, share back:

| Question | If yes → |
|---|---|
| Did total cancelled orders in IB drop materially today? | A is healthy in production |
| Did SOFI SHORT phantom auto-sweep at startup? | C is healthy |
| At 3:55-4:00 ET, were any closes silent? | E either did its job (PASS in stream) or still has a gap |
| Did any new entries fire after 3:55 ET? | D is broken — escalate |

## When to use which mode

- **One-shot** (`python -m backend.scripts.verify_v19_29`) — smoke
  checks at deploy time / morning prep.
- **`--watch`** — leave running on a second terminal during RTH so
  events surface as soon as they happen.
- **`--json`** — paste into chat with Emergent for tuning conversation.
- **`--probe-reconcile SYM`** — force-trigger gate B on a known
  orphan to prove wiring (only when no live position concerns).

## Failure modes & remediation

### F=FAIL: backend HTTP error
- `tail -n 200 /tmp/backend.log` — look for tracebacks at startup
- `sudo supervisorctl status backend` (if managed) or `ps aux | grep server.py`
- Confirm Mongo is reachable: `mongo --eval 'db.runCommand({ping:1})'`

### F=FAIL: missing reconciled_default_* fields
- Backend is pre-v19.24. Pull again, hard restart:
  ```bash
  pkill -f "python server.py" && cd /app/backend && \
    nohup python server.py > /tmp/backend.log 2>&1 &
  ```

### A/B/C/D/E=NO_DATA during RTH
- Open V5 → Diagnostics → Trail Explorer (v19.28). Filter for
  recent decisions and inspect Bot Thoughts section.
- Check `/api/diagnostics/recent-decisions?only_disagreements=true`
  to see if anything is being recorded at all.
- If `sentcom_thoughts` is empty: `emit_stream_event` is silently
  failing — escalate.

### A=NO_DATA but you saw duplicate cancellations in IB
- Confirms intent dedup wiring is silently broken. Lift git diff for
  `services/order_intent_dedup.py` and `services/trade_execution.py`.
- The hot path is line ~277 of `trade_execution.py` — must call
  `dedup.is_already_pending(...)` before `place_bracket_order`.

### B=NO_DATA after `--probe-reconcile`
- `bot_trades` materialization happened (good for orphan claim) but
  the stability gate didn't trigger (symbol was steady-state).
- To force trigger: pick a symbol you've JUST started observing —
  `record_ib_direction_observation` only flips stable after 30s.
