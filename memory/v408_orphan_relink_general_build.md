# v408 — generalized orphan relink (Seal #1) — 2026-06-24

## Why
The v407 taxonomy proved 87% of the −$5,714 orphan leak is 6 large positions that
lost bot tracking and got OCA-stopped on a synthetic 2% stop:
ARM −$1,398, ALNY −$1,106, SHLD −$815, UAL −$666, ARMG −$531, VRT −$465.
Operator confirmed (2026-06-24) **the bot is the SOLE opener of positions** → an
untracked IB position is ALWAYS a bot trade whose lineage broke; nothing is truly
"foreign", so we never flatten-as-foreign — we **restore tracking**.

Widened-window taxonomy split the leak:
- **Relinkable (has a real bot predecessor) −$3,216:** readopt_loop −$1,690,
  eod_reopen −$1,164, reaped_pending −$362.
- **Record-less −$1,897:** SHLD/UAL/VRT/UNP/CCI/ADI — NO bot_trade in 240 days
  (Seal #2, separate deeper bug — record vanished entirely).

## What shipped (Seal #1) — `services/position_reconciler.py`
GENERALIZES the v405 reaped-pending relink to ANY genuine bot predecessor:
- NEW `_find_recent_bot_predecessor(symbol, direction, abs_qty, avg_cost)` —
  READ-ONLY Mongo lookup for the most recent NON-synthetic bot_trade on
  (symbol, direction) within `RECONCILE_RELINK_ANY_WINDOW_MIN` (default 4320m=72h),
  ANY close_reason. Excludes `reconciled_orphan`/`reconciled_excess_slice` setups
  and `entered_by` starting with `reconciled` (never inherit a prior synthetic
  stop). Same directional-validity + qty-sanity (0.5–2.0×) guards as v405.
- NEW relink tier in `reconcile_orphan_positions`: when the v404 stale-pending
  relink does NOT match, inherit the predecessor's REAL stop/target/regime/TQS
  instead of the synthetic 2% OCA. Stamps `synthetic_source="relinked_predecessor"`,
  `entry_context.relinked_from_predecessor=True`, and emits
  `orphan_relink_predecessor_observe` / `orphan_relinked_predecessor` to
  `state_integrity_events`.

### Why it's safe
Strictly safer than a tight synthetic 2%: a wider real stop lets a still-valid
position survive; an already-fired stop is handled by the EXISTING `breached`
guard (closes at the real level, never re-rides a fresh tight OCA). Touches ONLY
the orphan stop/context computation on the adopt path — NO change to order
submission, `order_queue`, pusher, reaper, cancellation, `close_trade`, or
kill-switch. Reads `bot_trades` (Mongo) only.

### Env (defaults = ZERO behavior change on pull)
- `RECONCILE_RELINK_ANY_PREDECESSOR` = `observe` (default; log + forensic only) |
  `fix` (apply) | `off`.
- `RECONCILE_RELINK_ANY_WINDOW_MIN` = `4320`.

## Tests
`tests/test_orphan_relink.py` +4 (any-close-reason match, reconciled exclusion,
directional/qty guards, short match). Full: test_orphan_relink + test_orphan_taxonomy
= 22 passed. Reconciler imports clean; backend health 200.
Taxonomy `relink_coverage.state_integrity_events` now also counts the v408 events.

## ROLLOUT
1. Save-to-GitHub `main-2.0` → DGX pull → `./start_backend.sh --force` (observe).
2. After a session, watch the would-relink count:
   `curl -s ".../orphan-taxonomy/report?days=7" | python3 -c "import sys,json;print(json.load(sys.stdin)['report']['relink_coverage'])"`
   (or grep `🔗 [v407 RELINK observe]` in the log).
3. When the observe matches look right, set `RECONCILE_RELINK_ANY_PREDECESSOR=fix`
   in `backend/.env` + restart.

## NEXT
Seal #2 — record-less `true_foreign` (−$1,897): forensic on SHLD/UAL/VRT in
`ib_executions`/`order_queue` (where does the bot_trade record vanish?), then a
source fix + a contextless-adopt policy (wide protective stop / flatten). Then
pivot to **B** — system-wide entry quality (−0.306R/trade).
