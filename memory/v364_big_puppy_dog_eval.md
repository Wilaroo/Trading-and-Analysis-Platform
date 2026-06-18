# v364 — big_dog / puppy_dog doctrine rewrite EVALUATED → NOT SHIPPED (keep v361)

**Date:** 2026-06-18
**Decision:** Do NOT rewrite big_dog/puppy_dog to literal doctrine. **Keep the shipped v361 big_dog**
(min-price $10 + min-stop 1% tighten, +0.097R) and leave puppy_dog as-is. No code change.

## Why
Followed the v361b re-audit recommendation to test a doctrine-faithful rewrite (mid-day 11:00-13:30
window + above-prior-day-high gate + consolidation-base stop + declining volume + range-break entry +
scaled/Move2Move exit). Built `diag_v364_big_puppy_dog_doctrine.py` (1-min, LONG).

### Evidence (180d / 300-sym, 1-min)
| cut | n | win% | winsorAvg(±3) R |
|---|---|---|---|
| **shipped v361 (reference)** | 268 | 53% | **+0.097** |
| big_dog doctrine: mid-day + PDH + cons<50% + scaled | 6893 | 51% | +0.038 |
| big_dog: tighter coil 0.30 + fixed 2R | 6886 | 41% | +0.037 |
| big_dog: tighter coil 0.30 + 15-bar base + scaled | 4764 | 50% | +0.023 |
| puppy_dog: cons5, no-PDH, all-day, scaled | 82488 | 51% | +0.038 |
| puppy_dog: cons5, no-PDH, all-day, fixed 2R | 82488 | 39% | +0.040 |

**Every doctrine cut (+0.02..0.04R) is less than half of the shipped v361 (+0.097R).** The literal
doctrine underperforms the empirical tighten. Likely reasons: (1) the replay is a SUPERSET — it cannot
model the doctrine's quality filters (high RVOL, fresh news, >75%-above-open, HTF-resistance), which
are what make the human setup selective; (2) the mid-day breakout + scaled exit captures less than
v361's near-HOD ATR-target geometry on this universe.

## Action
- NO patch. v361 big_dog remains live. puppy_dog unchanged (also a thin proxy; live fires ~4/5d, ground
  truth n=2 — not worth a rewrite for +0.04R).
- Diag retained: `backend/scripts/diag_v364_big_puppy_dog_doctrine.py` (re-runnable if we later add the
  rvol/news/HTF quality gates to the replay).
- This closes the P1 "big_dog/puppy_dog doctrine rewrite" item as **evaluated → keep v361**.

## Note
The doctrine's value (mid-day + PDH structure) may still be capturable IF combined with the missing
quality filters; revisit only if a future shadow-logging stream provides live rvol/news context to
re-test. Not prioritized.
