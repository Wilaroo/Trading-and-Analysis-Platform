# Zombie-Trade Upstream Root Cause — Forensics Report
**Date:** 2026-05-06
**Author:** Read-only investigation per operator request (Issue 1 of v19.34.19 follow-up)
**Symbols affected:** FDX (369 sh), UPS (1223 sh) → 1592 naked IB shares total
**Suspected zombie trade IDs:** `b4d27b31`, `3f369929`, `95144a8d`
**Mode:** READ-ONLY — no code changes, no DB mutations.

---

## TL;DR

The "zombies" (`bot_trade.remaining_shares == 0` AND `bot_trade.status == OPEN`) are
created by **`v19.34.15b`'s own LIFO shrinker** —
`_shrink_drift_trades()` in `/app/backend/services/position_reconciler.py`
lines **1458–1522**.

When the share-count drift loop detects that IB has fewer shares than the bot
tracks (Case 2: partial external close), it peels shares off the most-recent
trade(s) LIFO. The peel sets `t.remaining_shares = new` (which can be `0`)
but never:

1. flips `t.status` to `TradeStatus.CLOSED`,
2. removes `t` from `bot._open_trades`,
3. stamps `closed_at` / `close_reason`,
4. moves `t` to `bot._closed_trades`.

So the trade keeps `status: OPEN` in memory and Mongo with `remaining_shares: 0`,
the bot's own drift detector sums `bot_q = sum(remaining_shares) == 0`, and the
**old** 15b case-distinction (`if sym not in bot_qty_by_sym or abs(bot_q) < 0.01: skip`)
hid this from the next pass. **15b created its own blind spot.** v19.34.19
patched the *detection*; this report identifies the *creation* bug.

---

## Evidence Chain

### 1. Mutation paths for `remaining_shares` (full inventory)

I grepped the entire backend for every site that mutates `remaining_shares` and
classified each one as **safe** (also flips status) or **leaky** (only mutates qty).

| File | Line | Path | Status flip? | Verdict |
|---|---|---|---|---|
| `position_manager.py` | 270 | OCA external close sweep | ✅ `_TS.CLOSED` set L255 | Safe |
| `position_manager.py` | 494–495 | manage-loop init when `rs == 0` | N/A (re-init) | Safe (only fires for fresh/uninitialized trades) |
| `position_manager.py` | 1115 | scale-out partial decrement | ✅ L1186 closes when `rs <= 0` | Safe |
| `position_manager.py` | 1378 | `close_trade()` full close | ✅ L1374 `TradeStatus.CLOSED` | Safe |
| `position_reconciler.py` | 284 | sync-position quantity update | N/A (re-init for new trade) | Safe |
| `position_reconciler.py` | 333 | sync-position auto-create | N/A (initial assignment) | Safe |
| `position_reconciler.py` | 397 | `close_phantom_position()` | ✅ L380 `TradeStatus.CLOSED` | Safe |
| `position_reconciler.py` | 411 | `close_phantom_position()` Mongo update | (mirrors above) | Safe |
| `position_reconciler.py` | 520 | quantity_mismatch repair | N/A (sync to IB qty, never zeros if IB has shares) | Safe* |
| `position_reconciler.py` | 824 | `_create_reconciled_orphan_trade` initial set | N/A (initial assignment) | Safe |
| `position_reconciler.py` | 1424 | `_close_drift_trades_zero` (Case 3, IB == 0) | ✅ L1420 `TradeStatus.CLOSED` | Safe |
| `position_reconciler.py` | **1491** | **`_shrink_drift_trades` LIFO peel (Case 2)** | **❌ NONE** | **🔴 LEAKY — zombie creator** |
| `position_reconciler.py` | 1582 | `_spawn_excess_slice` initial set | N/A (initial assignment for new trade) | Safe |
| `trade_execution.py` | 846 | confirm-time price recalc | N/A (re-init pre-fill) | Safe |

> *L520 (`quantity_mismatch`) only fires when IB has nonzero shares for the
> symbol. It cannot zero a trade. Verified by re-reading the surrounding
> conditional (`abs(ib_qty)` from L497).

**Single offender: `_shrink_drift_trades` L1484–L1494.**

### 2. The leaky code path — annotated

```python
# /app/backend/services/position_reconciler.py  L1484–L1494
for t in trades_lifo:
    old = int(abs(getattr(t, "remaining_shares", 0) or 0))
    if to_remove <= 0:
        applied.append({"trade_id": getattr(t, "id", None), "old": old, "new": old})
        continue
    take = min(old, to_remove)
    new = old - take                     # ← can be 0 when take == old
    t.remaining_shares = new             # ← qty mutated
    t.notes = (t.notes or "") + f" [v19.34.15b: shrunk {old}→{new} (LIFO)]"
    to_remove -= take
    applied.append({"trade_id": getattr(t, "id", None), "old": old, "new": new})
    # ⚠ MISSING when new == 0:
    #     t.status = TradeStatus.CLOSED
    #     t.closed_at = datetime.now(timezone.utc).isoformat()
    #     t.close_reason = "shrunk_to_zero_v19_34_15b"
    #     bot._open_trades.pop(t.id, None)
    #     bot._closed_trades.append(t)
```

### 3. How the zombies got produced (most likely sequence)

For each affected symbol (FDX, UPS), the historical sequence on **2026-05-04** to
**2026-05-06** was:

1. Bot opened multiple stacked slices (likely scale-in / Day 2 swing reentries) on
   FDX and UPS — each slice a separate `BotTrade` row in `_open_trades`.
2. At some point IB's view diverged from the bot's view. Probable causes (to be
   confirmed against the IB fill tape):
   - A bracket parent leg fired/got partially filled while the bot wasn't watching, OR
   - Day-roll: the bot persisted Day 2 trades correctly, but the IB position got
     trimmed externally (manual operator close, OCA-cleanup, EOD flatten, etc.).
3. The drift loop detected `IB_qty < bot_q` (Case 2) and called `_shrink_drift_trades`.
4. LIFO shrink peeled *all* shares off one or more entire slices (`take == old`,
   `new == 0`) — the slice's `remaining_shares` got set to `0` but
   `status` stayed `OPEN`. **Zombie born.**
5. Next drift pass: `bot_q = sum(remaining_shares) for FDX = 0`. IB still had
   the parent fill (the *non-shrunken* portion). Old 15b detection said
   `abs(bot_q) < 0.01 → skip`. Naked shares accumulate at IB.
6. Step 4-5 repeated as more partials hit, snowballing to 1592 sh.

> Verifying step 3 in production: every zombie-suspect trade should have a `notes`
> field containing the substring `"v19.34.15b: shrunk"` and a final `→0` token.
> Operator can confirm with the spot-check query in the **Confirmation Plan**
> below — no code change needed for the check.

### 4. Why v19.34.19's blind-spot patch is correct but incomplete

`v19.34.19` (lines 1244–1280) correctly *detects* zombie trades by enumerating
`bot_trades_by_sym` and looking for `remaining_shares == 0` even when `bot_q`
sums to zero. That's the right downstream catch.

**But the upstream fault still exists.** Until `_shrink_drift_trades` flips status
on full-peel, every Case-2 drift event continues to manufacture more zombies. The
v19.34.19 detector will keep cleaning them up, but:

- Audit trail noise (every shrink-to-zero generates a fresh "zombie" event the
  next pass).
- Wasted `reconciled_excess_slice` spawns (we'd be respawning a slice for
  shares that were "ours" the whole time — they were just orphaned by the
  shrinker bug).
- Drift event metadata is misleading (`zombie_trade_drift` is the *symptom*,
  `lifo_shrink_did_not_close` is the *cause*).

---

## Confirmation Plan (manual, operator-side, non-mutating)

The fork agent doesn't have DGX Mongo access. Operator can verify the diagnosis
in <2 min from the DGX shell:

```bash
cd ~/Trading-and-Analysis-Platform/backend
python3 -c "
from pymongo import MongoClient
import os, json
from dotenv import load_dotenv
load_dotenv()
db = MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
zombies = list(db.bot_trades.find(
    {'remaining_shares': 0, 'status': 'OPEN'},
    {'_id': 0, 'id': 1, 'symbol': 1, 'shares': 1, 'notes': 1, 'close_reason': 1, 'entered_by': 1, 'updated_at': 1}
))
print(f'TOTAL ZOMBIES: {len(zombies)}')
shrunk = [z for z in zombies if 'v19.34.15b: shrunk' in (z.get('notes') or '')]
print(f'  ↳ shrunk-by-15b (root cause): {len(shrunk)}')
print(f'  ↳ other (different upstream): {len(zombies) - len(shrunk)}')
for z in zombies[:10]:
    print(json.dumps(z, default=str))
"
```

**Expected outcome if root cause is correct:** the vast majority (≥90 %) of
zombies will have `'v19.34.15b: shrunk'` in their `notes`. Anything not in that
bucket points to a *second*, separate upstream leak that needs its own
investigation.

---

## Recommended Fix (NOT applied — for operator approval)

Replace the inner loop in `_shrink_drift_trades` (L1484–L1494) with a peel that
properly closes any slice that hits zero. **Pseudo-diff:**

```python
for t in trades_lifo:
    old = int(abs(getattr(t, "remaining_shares", 0) or 0))
    if to_remove <= 0:
        applied.append({"trade_id": getattr(t, "id", None), "old": old, "new": old})
        continue
    take = min(old, to_remove)
    new = old - take
    t.remaining_shares = new
    t.notes = (t.notes or "") + f" [v19.34.15b: shrunk {old}→{new} (LIFO)]"
    to_remove -= take
    applied.append({"trade_id": getattr(t, "id", None), "old": old, "new": new})

    # ── v19.34.20 (proposed) — close fully-peeled slices to prevent
    # zombie creation. Mirrors close_phantom_position() invariants.
    if new == 0:
        from services.trading_bot_service import TradeStatus
        t.status = TradeStatus.CLOSED
        t.closed_at = datetime.now(timezone.utc).isoformat()
        t.close_reason = "shrunk_to_zero_v19_34_15b"
        t.unrealized_pnl = 0
        # Compute realized_pnl for the peeled portion if exit price is known.
        # Conservative path: leave realized_pnl untouched (we don't have a
        # reliable exit price for the external partial close).
        if hasattr(bot, "_open_trades") and t.id in bot._open_trades:
            bot._open_trades.pop(t.id, None)
        if hasattr(bot, "_closed_trades"):
            try:
                bot._closed_trades.append(t)
            except Exception:
                pass
        # Stop-manager state cleanup (mirror close_trade L1401).
        try:
            sm = getattr(bot, "_stop_manager", None)
            if sm and hasattr(sm, "forget_trade"):
                sm.forget_trade(t.id)
        except Exception:
            pass
```

### Side effects to think through

1. **Realized P&L attribution.** We don't have a fill price for the external
   partial close that triggered the shrink, so the conservative path leaves
   `realized_pnl` unchanged on the peeled slice. The shares' P&L gets
   absorbed into the IB account-level realized number; the bot's own daily
   stat will under-count. Acceptable per the existing pattern in
   `_close_drift_trades_zero` (L1414, also doesn't compute P&L).
2. **Notes hygiene.** Every closed slice would carry a single
   `v19.34.15b: shrunk N→0 (LIFO)` token in notes plus
   `close_reason="shrunk_to_zero_v19_34_15b"` for grep-friendly post-mortems.
3. **Auto-test.** Add a unit test
   `test_shrink_drift_closes_zero_slices_v19_34_20.py` that:
   - Creates 2 BotTrades with `remaining_shares=100` each
     (`bot_q=200`).
   - Calls `_shrink_drift_trades` with `new_total_abs=50` (peel 150).
   - Asserts: oldest trade survives with `rs=50`, newest is fully closed
     with `status==CLOSED, rs==0, id not in bot._open_trades`.
4. **Backward compat.** Existing zombies in the DB (the 1592 already on the
   books) won't be auto-healed by this fix — they need the v19.34.19 healer
   path the operator already controls. Fix v19.34.20 prevents *future*
   zombies; v19.34.19 cleans the *existing* ones.

### Where to slot this in the version sequence

Operator already approved this work order:
- `v19.34.19` (zombie *detector*) — **shipped, dry-run verified**.
- `v19.34.20` (zombie *prevention* — this fix) — **PROPOSED, awaiting approval.**
- Then heal current zombies (operator's chosen mode from the prior `ask_human`).
- Then `v19.34.15a` (naked-position safety net for `bracket unknown` race).

---

## Open question for operator

The investigation flagged **one** primary leak (`_shrink_drift_trades`).
Confirmation step 4 above will tell us if **all** observed zombies trace back
to it. If a non-shrunk-flagged zombie exists, we have a second leak hiding
behind this one — likely candidates to inspect next:
- `position_manager._sweep_position_drift_v19_*` paths (older sweepers).
- `bracket_reissue_service.reissue_bracket_for_trade` if it ever resets
  `remaining_shares` mid-flight (verified read-only: it doesn't, only reads).
- `trade_execution.confirm_pending_trade` recalc path (L846) — only fires
  pre-fill, not a runtime risk.

If step 4 returns 100 % shrunk-flagged zombies, the fix above is the complete
upstream remediation.

---

## Files referenced (read-only)

- `/app/backend/services/position_reconciler.py` (lines 366–425, 1240–1280, 1414–1522)
- `/app/backend/services/position_manager.py` (lines 240–310, 480–540, 1080–1230, 1290–1410)
- `/app/backend/services/trade_execution.py` (lines 820–880)
- `/app/backend/services/bracket_reissue_service.py` (read-only, no zero-mutation paths found)

— end of forensics report —
