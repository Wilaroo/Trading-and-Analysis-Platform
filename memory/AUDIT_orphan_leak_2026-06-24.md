# AUDIT — reconciled_orphan execution leak (2026-06-24)

Read-only audit of the full order/fill/position lifecycle on BOTH sides before
any code change. Goal: confirm a fix won't break order processing, trade logging,
or trade management. No order-path code changed in this pass.

---

## A. DGX side (Linux) — lifecycle map

1. **Order submission** — `BOT_ORDER_PATH=pusher` (default). The bot pre-writes a
   `bot_trades` row `status=PENDING` (`pre_submit_at` stamped) BEFORE the broker
   call, then enqueues to Mongo `order_queue`. Orders are SUBMITTED by the Windows
   pusher (clientId=10), so **orders are owned by clientId=10**, not the DGX.
2. **Position / quote / account feed** — Windows pusher → `POST /api/ib/push-data`
   → `_pushed_ib_data` (in-memory) + Mongo `ib_live_snapshot.current`
   (routers/ib.py:918, 973). **This is the source of truth for positions on the DGX.**
3. **Fill tape** — `ib_executions` written by `ib_executions_persister` from
   `ibd._ib.fills()` — i.e. **direct IB (clientId=11), session-bound, skips silently
   when direct-IB is disconnected** (ib_executions_persister.py:151).
4. **Direct IB (clientId=11)** — a SEPARATE socket DGX→IB Gateway:4002
   (ib_direct_service.py). Used by the reaper guards / attribution / cancel.
   Comment at line 149: "the clientId=11 socket has been flapping 1-3x/day."
   It can read open orders (`reqAllOpenOrders`, one-shot) and positions
   (`_ib.positions()`), but **cannot cancel clientId=10's orders unless it is the
   IB master clientId** (v19.34.190 guard, line 307-337).
5. **Stale-pending reaper** (`_stale_pending_reaper_loop`, 60s, trading_bot_service.py:3706):
   reaps PENDING rows older than `PENDING_REAPER_MAX_AGE_S` (300s) with no
   `executed_at`. Three anti-orphan guards, **all depend on direct-IB**:
   - (a) `_attribute_pending_fills` (v236) — promote a filled PENDING → OPEN.
     `if ibd is None or not await ibd.ensure_connected(): return` (line 5131).
   - (b) `_reaper_should_skip_filled` (v234) — skip reap if IB shows a position the
     bot isn't tracking. `ib_pos_syms` gathered via direct-IB `get_positions()`
     (line 3766); empty when direct-IB is down → guard can never fire.
   - (c) cancel-first (v300) — cancel a still-working order before reap; keep
     tracking if it can't be cancelled. Uses direct-IB `get_open_orders` + `cancel_order`.
6. **Reconciler** (`reconcile_orphan_positions`, position_reconciler.py:1052+) —
   adopts an untracked IB position as `setup_type="reconciled_orphan"` with a
   **synthetic ~2% default stop + regime UNKNOWN + a fresh OCA** (line 1655+).
   It already has a "smart stop" lookup from recent rejection verdicts (1712-1799).
7. **Close** — OCA bracket fires → `oca_closed_externally_v19_31`
   (position_manager.py:422).

## B. Windows side — contract (from the DGX handlers; code not on this box)
- IB Gateway :4002. Pusher (clientId=10) streams market data AND submits orders by
  polling `/api/ib/orders/pending` → submit → `/api/ib/orders/result`. 4 turbo
  collectors (clientId 16-19). Pusher pushes positions (with avgCost), quotes,
  account, and orders to `/api/ib/push-data`.
- The DGX's direct-IB clientId=11 connects to this SAME Gateway:4002.

## C. The failure point (RCA, from the live report)
Guard-event counts over 120d: `pending_fill_attributed=2`,
`reaper_skip_likely_filled=2` (both effectively DEAD), `reaper_skip_working_order=278`
(ALIVE). Asymmetry: **direct-IB ORDER reads work; POSITION reads / attribution
barely fire.** Chain:
- bot PENDING fills at IB → fill never attributed back (`executed_at` stays None) →
- 300s later the reaper reaps it `stale_pending_auto_reaper` because the
  position-based guards (a)/(b) can't see the fill (direct-IB positions empty/
  flapping, or attribution disabled) →
- the reconciler adopts the live IB position as `reconciled_orphan` with a
  **synthetic 2% stop** — TIGHTER than the original thesis stop in **58/120** cases,
  regime UNKNOWN, losing context recoverable in **78/120** cases →
- OCA stops it on noise → `oca_closed_externally` (87 trades, **-21.67R**).
Median gap reap→orphan = **0.5 min** (same physical position).

## D. Runtime confirmation needed (read-only) — `GET /api/slow-learning/orphan-leak/diagnostics`
Reveals: direct-IB available/connected + `get_positions()`/`get_open_orders()`
counts + session fills; pusher `pushed_positions_count` + snapshot count/freshness;
`ib_executions` total/last_7d/latest; recent-orphan fill corroboration; and the env
flags (`BOT_ORDER_PATH`, `PENDING_FILL_ATTRIBUTION_ENABLED`, `PENDING_REAPER_*`,
`IB_DIRECT_*`). This decides config-vs-code and which fix to apply.

## E. Candidate fixes + blast-radius

### Fix A — Layer 2, SAFE (Mongo-only, reconciler stamp). RECOMMENDED FIRST.
When `reconcile_orphan_positions` spawns a `reconciled_orphan`, look up the most
recent matching predecessor `bot_trade` (reaped pending / recently closed, same
symbol+direction, recent window) and **inherit its entry_context (regime/TQS/thesis)
+ ORIGINAL stop/target** instead of synthetic 2%. Extends the existing v19.34.3
smart-stop lookup.
- Touches ONLY the orphan stop/context computation. Does NOT touch order
  submission, `order_queue`, pusher, reaper, cancellation, `close_trade`, kill-switch.
- Reads `bot_trades` (Mongo) only. Existing `breached` guard still applies.
- Risk: LOW. Worst case = orphan gets the wider ORIGINAL stop = the risk the trade
  was actually sized for. Env-gated observe→fix.
- Stops the bleed mechanism immediately; does NOT prevent orphan creation.

### Fix B — Layer 1, ROOT CAUSE (pusher-aware guards). After diagnostics.
Make `_attribute_pending_fills` + the reaper's `ib_pos_syms` **fall back to the
pusher position snapshot** (`_pushed_ib_data["positions"]` → `ib_live_snapshot.current`)
when direct-IB is empty, so a filled PENDING is promoted to OPEN (context intact)
and never becomes an orphan.
- Touches the reaper loop + `_attribute_pending_fills`. Submits/cancels NO orders;
  only changes reap-vs-promote. Match stays symbol+dir+qty+time (same as direct path).
- Risk: MEDIUM — must gate on pusher-snapshot FRESHNESS (a stale snapshot must not
  promote). Bounded blast radius: at worst a benign PENDING stays tracked.
  Env-gated `REAPER_PUSHER_FALLBACK`, observe-first.
- Fixes the root cause.

### Fix C — CONFIG (if diagnostics show direct-IB simply misconfigured/disabled)
If `PENDING_FILL_ATTRIBUTION_ENABLED` is off, or `IB_DIRECT_*` is misconfigured so
clientId=11 never holds a stable position subscription, the real fix may be config
(re-enable / fix host/port/clientId / master-clientId) — no code change.

## F. Recommended sequence
1. Run the diagnostics endpoint on the DGX (read-only) → confirm direct-IB status +
   attribution flag + fill-tape health.
2. Ship **Fix A** (safe) to stop the -R bleed immediately, env-gated observe→fix.
3. Decide Fix B vs Fix C for the root cause based on diagnostics; build observe-first.
