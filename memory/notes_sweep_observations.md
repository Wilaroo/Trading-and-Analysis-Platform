# PT/SL Sweep Observations — Final Results (2026-04-21)

User's 150-symbol sweep completed at 21:15 UTC on Spark. 68 configs saved to Mongo `triple_barrier_config`.

## Summary Table

34 unique (setup, bar_size) combinations × 2 sides = 68 configs.

### Balanced ✓ (66 of 68)
All 1-day setups collapsed to the same config: `pt=1.5 sl=1.5 max_bars=5` → ~28/44/28 class split (symmetric, flat-dominant).

Per-family picks:
- **SCALP**: 1min pt=3.0/sl=2.0/mb=30 (53/16/30); 5min pt=2.0/sl=2.0/mb=12 (31/38/30)
- **ORB**: 5min pt=2.0/sl=2.0/mb=12 (31/38/30)
- **GAP_AND_GO**: 5min pt=2.0/sl=2.0/mb=12 (32/38/30)
- **VWAP**: 5min pt=2.0/sl=2.0/mb=12 (32/38/30)
- **BREAKOUT**: 5min pt=2.5/sl=2.0/mb=24 (43/25/32); 1d pt=1.5/sl=1.5/mb=5
- **RANGE**: 5min pt=3.0/sl=2.0/mb=36 (50/19/31)
- **MEAN_REVERSION**: 5min pt=3.0/sl=2.0/mb=36 (50/20/30)
- **TREND_CONTINUATION**: 5min pt=3.0/sl=2.0/mb=40 (51/17/31); 1d pt=1.5/sl=1.5/mb=7 (34/31/35) ← cleanest
- **MOMENTUM**: 1h pt=2.5/sl=2.0/mb=14 (40/28/32); 1d pt=1.5/sl=1.5/mb=7 (34/31/35)
- **SHORT_SCALP / SHORT_ORB / SHORT_*** all balanced

### FALLBACK ✗ (2 of 68)
Only REVERSAL/5mins on both sides rejected the balance check, as flagged mid-sweep:

```
REVERSAL/5mins/long  pt=2.5 sl=2.0 mb=60 → DOWN=52%  FLAT=8%   UP=40%
REVERSAL/5mins/short pt=3.0 sl=2.0 mb=60 → DOWN=55%  FLAT=10%  UP=36%
```

**Hypotheses (revisit post-retrain):**
- `detect_reversal` firing on mid-move bars, not true pivots.
- Try requiring N bars of opposite direction *before* the pivot as an entry gate.
- Consider moving REVERSAL to 15-min / 1-hour where pivots are cleaner.
- Or split into `REVERSAL_LONG_OVERSOLD` (RSI<30 at entry) vs `REVERSAL_SHORT_OVERBOUGHT`.

## Interesting Patterns

1. **5-min horizons need LONG max_bars (12-60)** — expected for scalp setups; noise dominates short windows.
2. **1-day setups are remarkably uniform** — all converged to pt=1.5/sl=1.5/max_bars=5. Worth widening the sweep grid (pt 0.8-3.0, max_bars 3-15) post-retrain to see if finer alpha exists.
3. **TREND_CONTINUATION/1 day is the star** — balance=0.002 (near-perfect 1:1:1). Prioritize heavy weight in the portfolio allocator.
4. **SHORT_ORB is the only asymmetric setup** — long side peaks UP=38%, short side peaks DOWN=39%. Correctly directional by construction.
5. **SCALP/1 min** is present in the config but NOT currently wired into the setup-long/short workers (only 5-min is). Verify if this will actually get trained, or if it's a leftover config row.

## Post-Retrain Actions

1. **Run the setup coverage audit** (`backend/scripts/audit_setup_coverage.py`) to see which of the 35 taxonomy codes have journal data to warrant dedicated Phase 2E models.
2. **Delete REVERSAL/5mins** if scorecard grades D/F — or redesign the detector.
3. **Widen daily PT/SL grid** (pt 0.8-3.0, max_bars 3-15) and re-sweep daily setups.
4. **Add a `balance_healthy` flag** to `triple_barrier_config` rows: when `balance > 0.2`, mark `unhealthy_labels=True` and consider skipping that (setup, bar_size) combo in the next training cycle.
5. **Investigate SCALP 1-min wiring** — is it reaching a worker?
