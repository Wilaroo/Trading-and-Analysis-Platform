# v366 — P-WIRE Phase-2 readiness + regime diagnosis (2026-06-18)

## TL;DR — the PRD's "regime threshold too sensitive" diagnosis is WRONG. Do NOT recalibrate.

### What was claimed (PRD 2026-06-15)
> "classify_regime returns high_vol in ~91% of decisions because vol_expansion > 1.3 preempts
> trend evaluation — that gate is too sensitive for SPY's current vol regime." → proposed
> P0-CLASSIFIER recalibration 1.3 → ~1.5 in regime_conditional_model.py:96.

### What the data actually shows (diag_v366 + diag_v366b, READ-ONLY)
- `diag_v366_pwire_readiness.py` (paste.rs/OBDuI): 6149 shadow records / last 60d, **94.8% high_vol**,
  RESOLVED **92 / 200** (Phase-2 WAIT), **100% bar_size='5 mins'**, regime_model_available only
  1421/6149 (77% have NO trained variant to compare against). SPY *daily* vol_expansion calibration
  (226d): median **1.00**, `>1.3` fires only **15.9% of days** (>1.5 → 5.3%).
- `diag_v366b_regime_live_trace.py` (paste.rs/wjwyB) replicated the EXACT live pipeline
  (timeseries_service.classify_current_regime → SPY '1 day', dedup date_key, 30 most-recent):
  bars **clean / distinct / ordered / recent** (2026-05-05..06-17, no partial/dupe today-bar);
  **atr_5=11.69, atr_20=8.61 → vol_expansion=1.358 → HIGH_VOL is CORRECT today.**

### Corrected root cause
The classifier is working. **SPY genuinely is in a volatility-expansion regime right now**
(recent daily ATR 1.36× the 20-day). The 94.8% record-skew ≠ the 15.9%-of-*days* figure because
shadow records are **per-gate-fire** (high-vol days produce far more alerts/fires) and the recent
60d has been more volatile than the 226d average. Recalibrating 1.3→1.5 would BLIND the classifier
to real volatility (high_vol only 5.3% of days) — a misfix. **THRESHOLD LEFT UNCHANGED.**

### Real P-WIRE Phase-2 blockers (none are the threshold)
1. Resolved decisions 92/200 — pure time/data accrual.
2. Dominant `5min_high_vol` regime variant is QUARANTINED (PBO=1.00 overfit) → can't be the
   comparison model for the majority of records.
3. Trend variants are starved simply because the market isn't trending — by design.

### Decision
- ❌ No threshold recalibration (misdiagnosis closed).
- ✅ The one clean accelerator = **P1-MULTI-TF multi-bar-size shadow logging** in
  `confidence_gate._get_live_prediction` (today hardcodes bar_size='5 mins', L1462). Emit an
  additive `regime_shadows[]` across 1min/5min/15min (read-only, env-gated, backward-compatible
  with the existing `live_prediction.regime_shadow` single record). Accelerates corpus growth for
  all (bar_size,regime) cells. pwire_shadow_eval.py updated to consume the list.
- Phase-2 EDGE eval itself is time/data-gated — re-run diag_v366 in ~2 weeks; run pwire_shadow_eval
  once RESOLVED ≥ 200.

### Tooling shipped this session (read-only diags, on DGX)
- diag_v366_pwire_readiness.py (paste.rs/OBDuI)
- diag_v366b_regime_live_trace.py (paste.rs/wjwyB)
- extract_func_generic.py (paste.rs/jERWM) — generic file+method extractor (extract_func.py is
  hardcoded to enhanced_scanner.py).
