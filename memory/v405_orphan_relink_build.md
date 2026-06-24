# v405 — orphan re-link fix (reconciler inherits reaped pending's real bracket) — 2026-06-24

## Corrections to the 2026-06-24 audit (from DGX diagnostics)
- Order path is **`BOT_ORDER_PATH=direct`** (clientId=11), NOT the pusher. There is
  **no clientId=10** on this deployment. Pusher = clientId=15 (data push only),
  collectors = 16-19, bot orders+reads = 11, aux = 12. The master-clientId cancel
  concern does NOT apply (orders are owned by the same socket that reads/cancels).
- Direct-IB is connected & healthy most of the time (`get_positions=8`,
  `get_open_orders=16`, `ib_executions` 639 total / 386 last-7d). 12/20 recent
  orphans corroborated by a real IB fill within 15m.
- Leak is **ACTIVE, not legacy**: 2026-05 = 50 orphans / -12.19R; 2026-06 =
  70 orphans / -7.54R (per-trade damage dropped, likely the V320H OCA accounting).

## Refined root cause (direct-IB era)
direct-IB **flaps 1-3×/day**. When it's momentarily down, `_attribute_pending_fills`
+ the reaper position-skip guard both bail (`if not ensure_connected: return`). A
pending that crosses the 300s reap threshold during a flap is reaped
(`stale_pending_auto_reaper`) **and popped from `_pending_trades`**. The reconciler's
in-memory v185/v264 guards then can't match it → it adopts the live fill as a
synthetic orphan with a **tighter 2% stop** (58/120) → OCA stop-out → the -R.

## Fix (shipped, env-gated, observe by default)
`services/position_reconciler.py`:
- New READ-ONLY helper `_find_reaped_pending(symbol, direction, abs_qty, avg_cost)`:
  finds a recently-reaped (`close_reason ^stale_pending`, within
  `RECONCILE_RELINK_WINDOW_MIN`=90m) bot_trade on the same symbol+direction with a
  directionally-consistent stop and qty within 0.5x–2x. Returns its real
  stop/target/regime/entry_context.
- In `reconcile_orphan_positions`, after the v19.34.3 smart-stop block: if a match
  is found, prefer the bot's OWN bracket over synthetic defaults AND rejection
  verdicts. Stamps `synthetic_source="relinked_reaped_pending"`, inherits regime/TQS,
  appends provenance to `entry_context.reasoning`, and writes a
  `state_integrity_events` forensic row.
- **Env `RECONCILE_RELINK_REAPED_PENDING`**: `observe` (DEFAULT — logs + writes
  `orphan_relink_observe` event, NO behavior change) | `fix` (apply real stop) |
  `off`. Window: `RECONCILE_RELINK_WINDOW_MIN` (default 90).

### Blast radius
Touches ONLY the orphan adoption's stop/target/context computation. **No change to
order submission, order_queue, the reaper, cancellation, close_trade, EOD, or the
kill-switch.** Reads bot_trades (Mongo) + writes one forensic event. In `fix` mode
the orphan gets the WIDER original stop (the risk it was actually sized for); the
existing breach guard still applies (a wider stop can't be breached if the tighter
synthetic one wasn't). Default `observe` = zero behavior change.

### Tests
`tests/test_orphan_relink.py` (7) — matching logic. All suites: 18 passed.

### Observe → Fix rollout (DGX)
1. Pull + restart (default `observe`). Let it run; watch:
   `curl -s ".../orphan-leak/report?days=7" | python3 -c "import sys,json;print(json.load(sys.stdin)['report']['fill_race_guard_events'])"`
   → `orphan_relink_observe` count rising = matches being found that WOULD be fixed.
2. When satisfied, set `RECONCILE_RELINK_REAPED_PENDING=fix` in backend/.env, restart.
3. Verify new orphans show `synthetic_source="relinked_reaped_pending"` and the
   monthly leak trend flattens.
