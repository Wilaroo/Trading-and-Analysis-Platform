# PT/SL Sweep Observations — 2026-04-21

Raw log: user's 150-symbol sweep on Spark. Key takeaways to revisit **after** the first massive retrain.

## Findings

### 1. REVERSAL/5 mins hit FALLBACK for both sides
```
REVERSAL/5 mins/long  → pt=2.5 sl=2.0 max_bars=60 → DOWN=52.1% FLAT=8.2%  UP=39.7%  (FALLBACK)
REVERSAL/5 mins/short → pt=3.0 sl=2.0 max_bars=60 → DOWN=54.6% FLAT=9.9%  UP=35.5%  (FALLBACK)
```
- No pt/sl combo produced a balanced 3-class distribution.
- FLAT class collapsed to 8-10% — entries are on candles that are *already moving*, so the time barrier rarely fires.
- Hypotheses to test post-retrain:
  - Our `detect_reversal` may be firing on mid-move bars, not actual pivot candles.
  - Try requiring N bars of opposite direction *before* the pivot bar as an entry gate (don't label until exhaustion confirmed).
  - Consider moving REVERSAL to a larger bar_size (15-min or 1-hour) where pivots are cleaner.
  - Or split into `REVERSAL_LONG_OVERSOLD` (requires RSI < 30 entry) vs `REVERSAL_SHORT_OVERBOUGHT` (RSI > 70).

### 2. 5-min horizons need LONG max_bars (24-60) to balance
Expected for volatile scalp setups — noise dominates in 12-bar windows. Revisit whether:
- We should sub-divide 5-min setups by volatility regime (ATR quartile) to pick max_bars dynamically.
- Or collapse some 5-min profiles into 15-min ones.

### 3. 1-day setups are remarkably uniform
All 1-day setups converged on pt=1.5 / sl=1.5 / max_bars=5 with a clean ~28/44/28 split. Suggests either:
- (Good) Daily bars with small barriers truly capture directional intraday follow-through.
- (Bad) Sweep search grid may be too narrow on the daily side; a wider grid (pt 0.8-3.0, max_bars 3-15) could find finer alpha per setup.

### 4. TREND_CONTINUATION/1 day was best-balanced
```
TREND_CONTINUATION/1 day/long  balance=0.002 (near-perfect 34/31/35)
```
Suggests daily trend-following is where triple-barrier shines. Weight this model heavier in the portfolio allocator.

## Post-Retrain Actions

- After retrain, sort the 15-metric Scorecard grades and look at which setup/bar-size combos earned **A or B**.
  - Any setup grading D/F with these new labels is a candidate for REDESIGN or REMOVAL.
  - REVERSAL/5 mins is almost certainly going to grade poorly — flag it for removal unless Scorecard surprises us.
- Re-run the sweep grid wider on daily setups (pt 0.8-3.0, max_bars 3-15).
- Consider adding a "balance rejection" gate to the sweep: if no pt/sl combo hits balance < 0.2, mark the setup `unhealthy_labels=True` in the config and skip training that combo.
