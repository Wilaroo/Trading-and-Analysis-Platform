# Zombie-Trade Upstream Root Cause — Forensics Report (REVISED)
**Date:** 2026-05-06
**Author:** Read-only investigation
**Symbols affected:** FDX (276 sh of zombie alloc, 369 sh IB drift), UPS (885 sh of zombie alloc, 1223 sh IB drift)
**Confirmed zombie trade IDs:** `b4d27b31` (FDX 256), `3f369929` (FDX 20), `95144a8d` (UPS 885)
**Mode:** READ-ONLY — no code changes, no DB mutations.

> ⚠️ **REVISION NOTE:** The first draft of this report blamed
> `_shrink_drift_trades` (v19.34.15b LIFO peel) based on theoretical mutation-site
> analysis. **The DB spot-check disproved that** — none of the 3 actual zombies
> carry the `'v19.34.15b: shrunk'` token in `notes`, and the `share_drift_events`
> collection has zero records referencing these trade IDs. The shrinker IS still
> a latent leaky path (verified, no `status` flip on full peel) but it is **not**
> the active root cause of the current 1592-share IB drift. The actual root
> causes are below.

---

## TL;DR (Revised)

There are **TWO** distinct active upstream bugs, with **ONE** latent third:

1. **🔴 ROOT CAUSE A — Timeout path forgets to initialize shares**
   `trade_execution.py:631–651` — when broker call returns `status: 'timeout'`,
   the code stamps `status=OPEN`, `fill_price`, `executed_at`, and persists,
   but **never sets `trade.remaining_shares = trade.shares`** (or
   `original_shares`). Both fields stay at the dataclass default `0`. The
   trade goes to `_open_trades` and gets persisted as a zombie immediately.
   **Affects:** `3f369929` (FDX 20) + `95144a8d` (UPS 885) — both carry
   `[TIMEOUT-NEEDS-SYNC]` fingerprint. Net: **905 sh** of the IB drift.

2. **🟡 ROOT CAUSE B — Legacy orphan trade `b4d27b31`**
   Single trade with `entered_by: bot_fired` (should be
   `reconciled_external` if created post-v19.34.3) and
   `original_shares: 0, remaining_shares: 0`. Notes match the post-v19.34.3
   reconciler path, but the missing `entered_by` flip suggests this row was
   either created by an older codepath OR re-saved by a path that wiped
   the v19.34.3 fields. **Cannot pinpoint without git blame on
   `position_reconciler.py:_create_reconciled_orphan_trade`** (need history
   between 2026-05-04 and 2026-05-05). Single isolated event; manually
   close-able. Net: **256 sh** of the IB drift.

3. **🟠 LATENT LEAK — `_shrink_drift_trades`**
   `position_reconciler.py:1484–1494` — verified leaky (full LIFO peel
   sets `remaining_shares=0` without flipping `status`). Has not yet
   produced a zombie because no operator has triggered a Case-2
   `auto_resolve` shrink yet (zero `share_drift_events` with
   `shrink_detail`). Will become a zombie generator the moment v19.34.15b
   `auto_resolve` runs against a real partial external close. Should be
   patched preemptively.

---

## Evidence (DB-confirmed)

### Zombie roster (full doc dump from operator's DGX, 2026-05-06)

| Trade ID | Symbol | Dir | shares | rs | os | status | entered_by | notes (excerpt) |
|---|---|---|---|---|---|---|---|---|
| `b4d27b31` | FDX | LONG | 256 | 0 | 0 | open | **bot_fired** ← anomaly | "Reconciled from IB orphan — stop at 2.0%..." |
| `3f369929` | FDX | LONG | 20  | 0 | 0 | open | bot_fired | " [PRE-SUBMIT-v19.34.6] [TIMEOUT-NEEDS-SYNC]" |
| `95144a8d` | UPS | LONG | 885 | 0 | 0 | open | bot_fired | " [PRE-SUBMIT-v19.34.6] [TIMEOUT-NEEDS-SYNC]" |

Common fingerprint: `original_shares: 0` (dataclass default — never overwritten)
plus `remaining_shares: 0` (same). Confirms a path that fails to call
`trade.remaining_shares = trade.shares` and `trade.original_shares = trade.shares`
post-construction.

### Negative evidence (rules out earlier hypotheses)

- ✅ `share_drift_events` collection: **0 records** referencing any of these
  trade IDs → `_shrink_drift_trades` is NOT a contributor (current data).
- ✅ `bracket_lifecycle_events`: **0 records** for these trade IDs → not a
  bracket-lifecycle bug.
- ✅ `rejection_events`: **0 records** for these trade IDs → not a rejection-path
  artifact.
- ✅ No other collection references these IDs.

---

## Root Cause A — Detailed walkthrough

`/app/backend/services/trade_execution.py` lines **631–651**:

```python
elif result.get('status') == 'timeout':
    # TIMEOUT HANDLING: Order may still execute - save as pending for sync
    trade.status = TradeStatus.OPEN  # Assume it went through
    trade.fill_price = trade.entry_price  # Use intended price
    trade.executed_at = datetime.now(timezone.utc).isoformat()
    trade.entry_order_id = result.get('order_id')
    trade.notes = (trade.notes or "") + " [TIMEOUT-NEEDS-SYNC]"

    # Initialize MFE/MAE
    trade.mfe_price = trade.fill_price
    trade.mae_price = trade.fill_price

    # Move to open trades so bot tracks it
    if trade.id in bot._pending_trades:
        del bot._pending_trades[trade.id]
    bot._open_trades[trade.id] = trade

    # Update stats
    bot._daily_stats.trades_executed += 1

    await bot._save_trade(trade)

    logger.warning(...)

    # ⚠ MISSING:
    #     trade.remaining_shares = trade.shares
    #     trade.original_shares  = trade.shares
```

`BotTrade` dataclass (`trading_bot_service.py:617–618`):
```python
original_shares: int = 0   # default 0 — must be set explicitly
remaining_shares: int = 0  # default 0 — must be set explicitly
```

So a timeout-path trade ships to `_open_trades` AND to Mongo with rs=0, os=0.

The downstream "self-heal" lives in the manage loop
(`position_manager.py:493–496`):
```python
# Initialize remaining_shares if not set
if trade.remaining_shares == 0:
    trade.remaining_shares = trade.shares
    trade.original_shares = trade.shares
```

**But this only fires if the manage loop sees a fresh quote.** For the TIMEOUT
trades, the bot likely never got a fresh quote in time — the manage loop hits
`if not quote: continue` (L466) or `if quote_age_s > STALE_QUOTE_S: continue`
(L489) and the re-init is skipped. The trade rots as a zombie until v19.34.19
detects it.

---

## Root Cause B — `b4d27b31` anomaly

The doc shows:
- `entered_by: bot_fired` — should be `reconciled_external` after v19.34.3
  (`position_reconciler.py:850`).
- `original_shares: 0` — should be 256 after L825
  (`trade.original_shares = abs_qty`).
- Notes match L1018 (`f"Reconciled from IB orphan — stop at {default_stop_pct:.1f}%..."`)
  exactly.
- `executed_at: 2026-05-05T15:25:09Z` — 1 day after v19.34.3 was supposedly shipped.

The discrepancy means one of:

**Hypothesis B1 — Migrated from older codepath:** This row was *originally*
created by a pre-v19.34.3 reconciler version that only wrote notes, not
`entered_by` / `original_shares`. The May-6 `last_updated` is from an unrelated
re-save (e.g., the manage loop touching `current_price`).

**Hypothesis B2 — Save path overwrites with stale instance:** Some path
constructs a new `BotTrade(id=...)` (defaults rs=0, os=0, entered_by=bot_fired)
WITH the same id and saves it, clobbering the original row. Candidate paths:
- `trade_execution.confirm_pending_trade` (L820+) — re-recalcs shares but only
  if `current_price != entry_price`.
- A boot-time DB→memory rebuild that doesn't preserve `original_shares` if
  the legacy row didn't have it.

**Hypothesis B3 — `to_dict()` field ordering quirk:** Unlikely; `asdict()` from
dataclasses includes all fields, and `original_shares` IS a field.

I cannot disambiguate B1/B2 without:
- Git blame of `position_reconciler.py` between 2026-05-04 and 2026-05-05,
  AND
- Mongo oplog or `last_updated` history (not currently captured).

**Pragmatic call:** since this is a single legacy row, manual cleanup
(`auto_resolve` heal OR direct DB close) is fine. Real prevention work
should focus on Cause A.

---

## Recommended Fixes (NOT applied — for operator approval)

### Fix v19.34.20 — TIMEOUT path initialization (Root Cause A)

**File:** `/app/backend/services/trade_execution.py`
**Where:** inside the `elif result.get('status') == 'timeout':` block
(currently lines 631–651), AFTER `trade.entry_order_id = result.get('order_id')`
and BEFORE `bot._open_trades[trade.id] = trade`.

**Patch (~3 lines):**
```python
elif result.get('status') == 'timeout':
    trade.status = TradeStatus.OPEN
    trade.fill_price = trade.entry_price
    trade.executed_at = datetime.now(timezone.utc).isoformat()
    trade.entry_order_id = result.get('order_id')
    trade.notes = (trade.notes or "") + " [TIMEOUT-NEEDS-SYNC]"

    # ── v19.34.20 (2026-05-06) — initialize share-tracking fields on
    # timeout. Pre-fix the BotTrade dataclass defaults of
    # remaining_shares=0 / original_shares=0 stayed at 0 because the
    # timeout block never overwrote them, and the manage-loop self-heal
    # at L494-496 of position_manager.py only fires when a fresh quote
    # arrives — TIMEOUT-NEEDS-SYNC trades often go quote-stale before
    # that, leaving them as zombies (status=OPEN, rs=0). Forensic:
    # 2026-05-06 spot-check found 905sh stuck across 3f369929 + 95144a8d.
    trade.remaining_shares = int(trade.shares)
    trade.original_shares = int(trade.shares)

    trade.mfe_price = trade.fill_price
    trade.mae_price = trade.fill_price

    if trade.id in bot._pending_trades:
        del bot._pending_trades[trade.id]
    bot._open_trades[trade.id] = trade
    bot._daily_stats.trades_executed += 1
    await bot._save_trade(trade)
    logger.warning(...)
```

**Side effects:** none. We're filling fields the rest of the system already
expects to be populated; the manage loop's L494 self-heal becomes a fallback
instead of the only path.

### Fix v19.34.20b — Latent shrinker leak (precautionary)

**File:** `/app/backend/services/position_reconciler.py`
**Where:** `_shrink_drift_trades` inner loop, currently L1484-1494.
**Patch:** add a `if new == 0:` block that flips `status`, removes from
`_open_trades`, and appends to `_closed_trades`. (Same patch detailed in
the original report — applies preemptively before the shrinker can produce
real zombies.)

### Heal current zombies (separate from the prevention fix)

For the 1161 sh of zombie BotTrades + 1592 sh of IB drift:
- **Aggressive (a):** run `POST /api/trading-bot/reconcile-share-drift`
  with `{"zombie_detect_only": false, "auto_resolve": true}`. v19.34.19
  spawns `reconciled_excess_slice` BotTrades (with default 2% SL / 2R PT,
  `close_at_eod=True`) and marks the 3 zombies CLOSED. ✅ Cleanest.
- **Conservative (b):** manually flip the 3 zombie rows to status=CLOSED in
  Mongo, rely on next normal orphan-reconcile pass to bracket the IB shares.
- **Manual (c):** flatten 1592sh at IB Gateway, then close zombie BotTrades.

---

## Confirmation Plan (already executed)

✅ `scripts/zombie_root_cause_spotcheck.py` ran on DGX:
- Total zombies: 3 (case-corrected for status='open')
- Shrunk-by-15b: 0 → original hypothesis disproven
- TIMEOUT-NEEDS-SYNC bucket: 2 → Root Cause A confirmed
- Reconciled-orphan bucket: 1 → Root Cause B (legacy/unknown subset)

---

## Files referenced (read-only)

- `/app/backend/services/trade_execution.py` (L395–445 PRE-SUBMIT, L615–680
  post-broker-call branch including the leaky TIMEOUT path)
- `/app/backend/services/trading_bot_service.py` (L583–746 BotTrade dataclass,
  fields with default-0 that bite us)
- `/app/backend/services/position_manager.py` (L440–496 manage-loop quote
  guard + self-heal, L1080–1230 scale-out close path, L1294–1410 close_trade)
- `/app/backend/services/position_reconciler.py` (L770–870 orphan create,
  L1244–1280 v19.34.19 zombie detect, L1414–1522 drift-trade actions
  including leaky `_shrink_drift_trades`)
- `/app/backend/scripts/zombie_root_cause_spotcheck.py` (READ-ONLY diag tool
  added this session)

— end of revised forensics report —
