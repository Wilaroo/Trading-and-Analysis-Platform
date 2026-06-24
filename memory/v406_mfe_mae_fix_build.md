# v406 — MFE/MAE writer fix (P1) — 2026-06-24

## Bugs (both reproduced)
1. **Catastrophic MAE corruption.** The manage-loop MFE/MAE block
   (`position_manager.py` ~935) tracked `mfe_price`/`mae_price` from
   `trade.current_price` with **no `<=0` guard** (unlike the unrealized_pnl block
   above it, v19.34.226). A stale/missing/zero quote — common for freshly-adopted
   orphans or a symbol dropped from the push — set `mae_price=0` →
   `mae_r=(0-fill)/risk ≈ -50R`, and it **stuck forever** (0 < any later price).
   This is the "MAE -3R while closing at -0.06R" symptom.
2. **winner_capture > 1.0.** Sparse manage ticks under-sample the true MFE, so
   `realized_r > mfe_r` → capture `r/m > 1.0` (impossible). The close-time
   backfill only filled mfe/mae when they were exactly 0, so an under-sampled
   non-zero mfe stayed wrong.

## Fixes
- `position_manager.py`: guard the MFE/MAE block with `... and _cp and _cp > 0`
  (only track on a valid mark). Prevents NEW corruption.
- `pnl_compute.py` `_backfill_excursion_floor`: now takes the MORE-EXTREME of
  (tracked peak, realized floor) — `mfe_r = max(tracked, max(0,realized))`,
  `mae_r = min(tracked, min(0,realized))`. Never shrinks a real peak; guarantees
  mfe_r ≥ realized favorable and mae_r ≤ realized adverse → kills capture > 1.0.
- `mfe_mae_study.py`: drops physically-impossible excursions (`|R| > 10`) from
  legacy corruption (reports `corrupt_excursions_dropped`) and clamps per-trade
  winner_capture to ≤ 1.0 (`r / max(m, r)`) so the verdict is trustworthy on
  mixed pre/post-fix data.

## Scope / blast radius
Writer + read-model only. No change to order submission, the reaper, the
reconciler, close logic, or kill-switch. Historical corrupt rows are NOT
rewritten (the fix prevents new corruption; the study excludes the old garbage).
An optional one-time historical repair can be added if wanted.

## Tests
`tests/test_mfe_mae_fix.py` (6) — excursion_floor long/short/winner/loser/bad-price,
winner_capture clamp. Full suite: 24 passed. Live `/api/slow-learning/mfe-mae/report` OK.

## Why it matters / unblocks
- The mfe-mae report is now trustworthy → tells us per-horizon
  entry_problem vs exit_giveback → unblocks the **time-decay exit study** AND the
  **orphan stop-width decision** (does a 2%-stopped trade recover? = MFE after stop).
