# Re-audit: `big_dog` & `puppy_dog` code vs SMB cheat-sheet doctrine

**Date:** 2026-06-18  **Trigger:** operator flagged that v361 big_dog was tuned off code+replay
without consulting the cheat sheets. This doc compares the LIVE code to doctrine. Read-only audit.

---
## A. Big Dog Consolidation — doctrine (The_Big_Dog_Consolidation_Cheat_Sheet.pdf)
- **Context:** in-play stock, strong opening drive, **fresh news catalyst**, high RVOL (way above avg),
  **>75% of day's trades above the open**. Pattern = **WEDGE / FLAG / PENNANT** *holding above the
  PRIOR-DAY HIGH*.
- **Time of day:** **MID-DAY — break triggers 11:00 AM – 1:30 PM ET.**
- **Consolidation:** volume **decreases** during the wedge/flag (≤50% of prior avg). Pattern must be
  **≤50% of the day's range** (else "sloppy" → invalid). Never if pattern top is **below a key HTF
  resistance**; odds drop if pattern is below upper-1/3 of day range or below VWAP.
- **Entry:** aggressive buy on the **break above the TOP of the wedge/flag/pennant** (don't wait for
  bar close).
- **Stop:** **.02 below the LOW of the BASE** of the pattern. **Hard stop, ONE-AND-DONE.**
- **Exit:** **Move2Move** — first move fast, pullback must hold 50% of the move (ideally upper 1/3),
  second wave, then **exit entire position on a double-bar-break lower after the second wave.**

### Live `_check_big_dog` (post-v361) vs doctrine
| Element | Doctrine | Live code | Verdict |
|---|---|---|---|
| Time window | **11:00–13:30 ET (mid-day)** | **none — fires all day** | ❌ MISMATCH (biggest gap) |
| Above prior-day high | required | not checked | ❌ missing |
| Pattern | wedge/flag/pennant ≤50% of day range | `daily_range_pct<2%` (abs intraday range) | ⚠️ proxy, different concept |
| Near top of pattern | break of pattern top | `dist_from_hod<1%` + trigger=HOD | ✅ approximate |
| Vol decrease in cons. | ≤50% of prior avg | `rvol>=1.2` (daily) only | ⚠️ partial |
| Stop | **.02 below base/consolidation low** | `ema_9-0.02` ATR-floored | ❌ different anchor |
| Exit | Move2Move double-bar-break trail | **fixed target HOD+1.5·ATR** | ❌ different |
| v361 adds | — | price≥$10, min-stop≥1% | ✅ empirically +EV (slippage cut) |

**Conclusion (big_dog):** v361 is a **simplified, empirically +EV proxy** (replay: +0.097R win53% n=268
after slippage gates), but it is **NOT doctrine-faithful**. The two structural gaps most likely to
matter: (1) **no mid-day window** — the code fires the "consolidation near HOD" pattern morning &
afternoon, whereas doctrine is an 11:00–13:30 trade; (2) **fixed HOD+1.5ATR target vs a Move2Move
double-bar-break trail** (caps the winners the doctrine is designed to ride). Recommend a future
**v36x big_dog doctrine rewrite** (mid-day gate + above-PDH + consolidation-base stop + double-bar-break
trail) evaluated via a doctrine replay, same as gap_give_go v362b. v361 stays live in the meantime
(it's +EV and the slippage gates are doctrine-agnostic improvements).

---
## B. Puppy Dog Consolidation — doctrine (SMB Puppy+Dog+Consolidation+Cheat+Sheet.pdf)
- Smaller/faster sibling of big_dog: a **small, distinct consolidation after a break of a key level**,
  traded in the **continuation direction** of the initial range break. Decreasing volume during the
  consolidation (indecision). Best in **clear trends**; avoid choppy/sideways.
- **Entry:** break of the consolidation range in the continuation direction, with **volume confirming**.
- **Stop:** **just outside the consolidation range**; trail as new levels form.
- **Target:** **measured move** from the consolidation; **scale out** at key levels.
- (The SMB sheet is qualitative — no minutes/%/RVOL thresholds, no explicit time-of-day, no PDH gate.)

### Live `_check_puppy_dog` vs doctrine
| Element | Doctrine | Live code | Verdict |
|---|---|---|---|
| Consolidation-range break | core | `daily_range_pct 0.5–1.5%` + `dist_from_hod<0.5%` | ⚠️ proxy (no range object) |
| Continuation of prior break | required | not modeled | ❌ missing |
| Vol confirm on break / decline in cons. | required | `rvol>=1.5` (daily) | ⚠️ partial |
| Stop | just outside consolidation range | `cp-0.3·ATR` | ❌ different anchor |
| Target | measured move + scale-out | `HOD+1.0·ATR` fixed | ⚠️ different |

**Conclusion (puppy_dog):** also a loose proxy; same structural gaps as big_dog (no real range object,
ATR stop vs range stop, fixed target vs measured-move/scale). Ground truth is too thin to act on
(n=2, +0.3R). **Left unchanged** for now. If we do the big_dog doctrine rewrite, puppy_dog should be
rebuilt in the same pass (it's literally the faster/smaller variant) or folded into it.

---
## Net recommendation
- **Keep v361 big_dog live** (empirically +EV; slippage gates are pure improvements).
- **Log a P1 "big_dog/puppy_dog doctrine rewrite"** to ROADMAP: mid-day window (11:00–13:30), above-PDH
  gate, consolidation-range detection with declining volume, **base/range stop**, **double-bar-break
  Move2Move trail**. Evaluate with a doctrine replay before shipping (template = gap_give_go v362b).
- This audit is why the **cheat sheet must be consulted BEFORE the replay** for the remaining queue
  (`gap_give_go` now, `spencer_scalp` next).
