# Mid-Bar Tick Eval — Activation Playbook (v19.34)

**Date shipped:** 2026-05-04
**Risk level:** Medium-High (touches live manage-loop close path)
**Default state:** OFF (`MID_BAR_TICK_EVAL_ENABLED=false`)

---

## What this does

Without this feature, when a stop is hit mid-bar, the close fires on the
*next* manage-loop tick (~5-15s later) or when the next bar closes
(~30-60s later, depending on timeframe). With this feature ON, the bot
subscribes to per-symbol L1 quote ticks via the in-memory
`quote_tick_bus` and re-evaluates the stop trigger on every fresh quote
(~50ms cadence). When a tick crosses the stop, the close fires
immediately — saving the next-cycle latency.

Mid-bar eval **only** checks fixed/trailing stops. It does NOT:
- Trail stops (trailing recalc stays on bar-close cadence).
- Scale out (still bar-close cadence).
- Evaluate entries (entries still wait for bar-close to avoid wicks).

The bar-close stop check stays in place as a safety net even when this
feature is ON.

---

## Pre-flight checklist (BEFORE flipping the flag)

Run these in order. ALL of them must pass before turning Phase 3 on.

### 1. Confirm the bus is publishing

```bash
curl -s ${BACKEND_URL}/api/ib/quote-tick-bus/health | jq
```

Expect during RTH:
- `enabled: true`
- `publish_total > 0` and growing each minute (re-run the curl after 60s)
- `drop_total: 0` (or extremely low — well under 1% of `publish_total`)
- `active_symbols: 0` (Phase 3 is OFF; nobody subscribes)
- `total_subscribers: 0`

**Red flags:**
- `publish_total: 0` → pusher isn't reaching the bus. Check:
  - Pusher health: `curl ${BACKEND_URL}/api/ib/pusher-health`.
  - Pusher push log on Windows.
- `enabled: false` → someone flipped `QUOTE_TICK_BUS_ENABLED=false`.
  Don't proceed; Phase 3 needs the bus.

### 2. Watch for ~30 minutes of RTH

Aim for at least 30 minutes of pusher pushes during a normal RTH
session. The bus should accumulate tens of thousands of publishes
across 40+ symbols with zero drops.

### 3. Confirm the manage-loop is healthy on the existing path

The mid-bar eval is *additive* — it doesn't replace the bar-close
stop check, it just front-runs it. So the existing manage-loop must
already be doing its job correctly:

- Open positions tab shows correct PnL (no stuck rows).
- Day Tape shows realized PnL stamping after closes.
- No phantom sweeps in the last 24h (`/api/diagnostics/forensics`).

If anything's broken on the existing path, fix that first.

---

## Activation

```bash
# On the DGX machine (Linux):
echo "MID_BAR_TICK_EVAL_ENABLED=true" >> /app/backend/.env
sudo supervisorctl restart backend
```

**Alternative env vars:**
- `MID_BAR_TICK_RECONCILE_S=2.0` — how often the lifecycle task walks
  `_open_trades` to spawn/cancel subscribers. Default 2s. Smaller =
  newer trades get a subscriber faster but more CPU. Leave at default.

---

## Verification (AFTER flipping the flag)

### 1. Subscribers are spawning

After bot boot + at least one open trade:

```bash
curl -s ${BACKEND_URL}/api/ib/quote-tick-bus/health | jq
```

Expect:
- `active_symbols` ≥ #(open trades). ONE subscriber per (trade_id, symbol).
- `total_subscribers` matches.
- `per_symbol[].subscribers` ≥ 1 for symbols with open trades.

### 2. Logs confirm wiring

In the backend logs, look for:

```
[v19.34 MID-BAR TICK] +sub trade_id=<id> sym=<SYM>
```

One line per open trade within 2-5s of the trade opening. When the
trade closes:

```
[v19.34 MID-BAR TICK] -sub trade_id=<id>
```

### 3. Mid-bar fire happens

When a stop is hit mid-bar, you'll see the warning log:

```
[v19.34 MID-BAR STOP] AAPL long trigger=$148.5000 <= stop=$148.7500
(mode=original); firing close NOW (saved ~next-cycle latency)
```

The close is then fired through the **same code path** as bar-close
stops, so realized PnL, sweeps, and journaling all behave identically
to a bar-close fire. The only difference is the `close_reason` is
stamped `stop_loss_mid_bar_v19_34` (or `stop_loss_<mode>_mid_bar_v19_34`
for trailing stops) so you can filter Day Tape / Forensics for them.

---

## Rollback

```bash
# On DGX:
sed -i 's/MID_BAR_TICK_EVAL_ENABLED=true/MID_BAR_TICK_EVAL_ENABLED=false/' /app/backend/.env
sudo supervisorctl restart backend
```

Within 5s of restart, all subscriber tasks are cancelled and the bot
reverts to bar-close stop eval. The bus itself keeps publishing (it's
still useful for monitoring), it just has no consumers.

If you need a HARDER kill (e.g. the bus itself is misbehaving):

```bash
echo "QUOTE_TICK_BUS_ENABLED=false" >> /app/backend/.env
sudo supervisorctl restart backend
```

This makes `publish/subscribe` no-ops at the source, so the bridge in
`receive_pushed_ib_data` does nothing. The bot reverts to its v19.33
behavior entirely.

---

## Monitoring during operation

### Healthy

- `drop_rate_pct` < 0.1% — consumers keep up with the producer.
- `active_symbols` matches `len(_open_trades)` — every open trade has
  a subscriber.
- A small number of `mid_bar_v19_34` rows in Day Tape — you should see
  these on stop-hit days.

### Unhealthy

- `drop_rate_pct` > 5% → the consumer (`evaluate_single_trade_against_quote`)
  is too slow. Investigate `close_trade()` latency. May indicate
  database lock contention, IB pusher RPC slowness, or a stuck
  position_reconciler.
- `active_symbols` < `len(_open_trades)` for >10s → lifecycle reaper
  isn't keeping up. Check the bot's main event loop for blocking calls.

---

## Known limitations

1. **No tick coalescing.** Each tick triggers a fresh eval. During a
   wild market open (5,000 ticks/sec on SPY), this *could* dominate
   the event loop. Mitigation: the latest-N drop policy keeps the
   queue at 8 ticks max, so the consumer only ever runs the eval at
   most 8 times per slow cycle.

2. **Stop-trail and scale-out stay on bar-close cadence.** If you
   want sub-bar trailing, that's a separate change; this only handles
   stop-hit detection.

3. **Multi-leg positions.** If a trade has multiple legs (e.g. partial
   fills creating multiple `bot_trades` rows), each gets its own
   subscriber. The eval is per-row, so partial-fill behavior matches
   the existing manage-loop.

4. **Restart wipes bus state.** If the backend restarts mid-session,
   the lifecycle reaper re-subscribes within ~5s. No durability
   layer; tick streams are stateless.

---

## File map

- `services/quote_tick_bus.py` — the bus itself.
- `routers/ib.py:receive_pushed_ib_data` — pusher → bus bridge (Phase 2).
- `routers/ib.py:get_quote_tick_bus_health` — `/api/ib/quote-tick-bus/health`.
- `services/position_manager.py:evaluate_single_trade_against_quote` — the per-trade eval.
- `services/trading_bot_service.py:_midbar_tick_lifecycle_loop` — the reaper task.
- `tests/test_v19_34_quote_tick_bus_midbar_stop.py` — 25 pytests covering all paths.
