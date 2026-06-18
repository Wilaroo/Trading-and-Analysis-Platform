# v365 — Scaled / measured-move EXIT-POLICY evaluation — VERDICT: KEEP flat-2R (no build)

**Date:** 2026-06-18
**Scope:** Decide whether to build a scaled measured-move exit (1R/2R/3R) for `spencer_scalp`
and a Move2Move trail for `gap_give_go` (the P1 item deferred by v362/v363, which shipped a
**detector-only flat 2.0R target**).
**Method:** `backend/scripts/diag_v365_scaled_exit_eval.py` (READ-ONLY, 1-min bars, 180d / 300-sym).
Reconstructs the EXACT shipped v362/v363 entries, then runs the SAME entry set through 5 exit
policies head-to-head: `flat_2R` (shipped), `scaled_123` (⅓@1R/2R/3R, BE-after-1R), `dbb_trail_100`
(pure double-bar-break trail), `m2m_half_1R` / `m2m_half_mm` (SMB "half first leg / half second
leg": ½ off at 1R / at the consolidation-band measured-move, trail ½ on double-bar-break, BE).

## Evidence (winsor ±3R, then ±2R robustness)
| Setup | Policy | n | win% | winsorAvg(±3R) | winsorAvg(±2R) | medR |
|---|---|---|---|---|---|---|
| spencer_scalp | **flat_2R (shipped)** | 17743 | 45% | **+0.065** | **+0.064** | −0.167 |
| spencer_scalp | scaled_123 | 17743 | 52% | +0.063 | +0.063 | +0.113 |
| spencer_scalp | dbb_trail_100 | 17743 | 42% | +0.047 | +0.024 | −0.114 |
| spencer_scalp | m2m_half_mm | 17743 | 55% | +0.061 | +0.054 | +0.250 |
| gap_give_go | **flat_2R (shipped)** | 459 | 46% | **+0.204** | **+0.204** | −0.364 |
| gap_give_go | scaled_123 | 459 | 56% | +0.196 | +0.196 | +0.333 |
| gap_give_go | dbb_trail_100 | 459 | 40% | +0.100 | +0.017 | −0.364 |
| gap_give_go | m2m_half_mm | 459 | 60% | +0.179 | +0.155 | +0.406 |

## Verdict — KEEP flat-2R for BOTH setups; do NOT build the scaled PM layer
- On **mean EV**, `flat_2R` and `scaled_123` are a **statistical tie** for both setups
  (Δ −0.002 to −0.008R). No policy clears the +0.03R build-justification gate.
- **`flat_2R` is NOT a fat-tail artifact** — its mean is rock-stable across winsorization
  (gap_give_go identical +0.204 at ±3R and ±2R; spencer +0.065→+0.064). The trail / m2m
  policies are the tail-dependent ones (they DECAY under ±2R). This refuted the initial
  "flat-2R is fragile" hypothesis.
- The pure double-bar-break trail (`dbb_trail_100`) clearly **LOSES** for both setups — drop it.
- Only non-EV argument for `scaled_123`: higher win% (52–56% vs 45–46%) + positive median at
  equal expectancy → smoother equity / fewer losing streaks (lower kill-switch trip risk for an
  unmanaged bot). Operator chose **NOT** to pursue this (option A) — no EV justification to touch
  the safety-adjacent scale-out engine.

## Status
- No code change shipped. `spencer_scalp` and `gap_give_go` remain on the shipped flat-2.0R target.
- Scale-out/measured-move exit work is **CLOSED as "evaluated, not worth it"** unless future live
  data shows a kill-switch-streak problem (then re-open with a drawdown/streak sim — option B,
  deferred).
- Tooling kept for future re-eval: `diag_v365_scaled_exit_eval.py` (paste.rs/Mv5Va).

## Also this session
- P0 "suppressed setups still firing live" = **FALSE ALARM / CLOSED**. `diag_v365_leak_recency.py`
  (paste.rs/6nTwV) proved every squeeze/vwap_bounce/fashionably_late fire predates its suppression
  COMMIT (v354@17:27ET, v357@20:50ET, v359@21:42ET all committed AFTER the latest fire @15:56ET
  June 17) — i.e. stale pre-deploy residue from June 17 RTH, not a live leak. Gold-standard
  re-confirm pending: run `diag_v365_leak_recency.py --hours 2` mid-RTH (expect 0 fires).
