# Model-Family Audit — 2026-06-10 (session continuity note)

DB: tradecommand · collection: timeseries_models (110 promoted models)
Method: code-level inference-consumption grep + per-class recall (collapse) from stored metrics.

## Headline
- 110 promoted models → **59 DEAD at inference**, **46 class-collapsed** (min per-class recall < 0.10).
- "Accuracy" was masking majority-class collapse across most non-direction families.

## Family table
| family | n | avg_acc | collapsed | inference |
|---|---|---|---|---|
| setup_models | 34 | 0.480 | 3/34 | via ensemble/consensus |
| regime_conditional (`*_high_vol`/`*_bull_trend`/`*_bear_trend`/`*_range_bound`) | 28 | 0.572 | 9/28 | **DEAD** |
| exit_timing | 10 | 0.455 | 1/10 | **DEAD** (exits 100% rule-based) |
| ensemble (`ensemble_<setup>`) | 10 | 0.610 | **10/10** | **LIVE** (gate +15 meta-labeler) |
| direction_predictor_{tf} (base) | 7 | 0.528 | 2/7 | **LIVE** (core) |
| volatility (`vol_predictor_*`) | 7 | 0.775 | 7/7 | DEAD (P1 target fix shipped) |
| risk_of_ruin | 6 | 0.617 | 6/6 | DEAD |
| gap_fill | 5 | 0.941 | 5/5 | DEAD (redesign pending) |
| sector_relative | 3 | 0.545 | 3/3 | DEAD |

## CORRECTION (2026-06-10, after diag_ensemble_pwin_live.py)
- The ensemble "10/10 collapsed" was a FALSE POSITIVE. Live p_win is healthy and
  DISCRIMINATING (median 0.51, p10 0.40, p90 0.78, std 0.143, span 0.16-0.91;
  per-ensemble medians differentiated: vwap 0.82, meanrev 0.77, gap 0.64, trend
  0.40). argmax-recall is the WRONG lens for a graded-probability meta-labeler.
  P-LIVE-1 = no action. Real collapse count is ~36 (not 46): the genuinely
  collapsed families have recall_down EXACTLY 0.00 and are consumed as argmax/
  binary (vol_predictor 7, gap_fill 5, risk_of_ruin 6, sector_relative 3, + some
  direction/regime variants). The collapse FLAG is only valid for argmax-consumed
  models, not graded p_win ones.

## Key findings
1. LIVE: ensemble is HEALTHY (see correction above). 2/7 core direction collapsed (argmax — real).
   - Root cause = imbalanced binary target (low win base-rate → collapse to majority), same as vol/gap.
   - P0 collapse gate (v19.34.312, shipped) covers TimeSeriesGBM._save_model → rejects collapsed on retrain.
2. Big wasted edge: ~18 regime_conditional models are HEALTHY two-sided (acc 0.52–0.78) but DEAD.
   Strong ones: 1min_bull_trend 0.783, 1min_bear_trend 0.760, 1min_range_bound 0.679, 1min_high_vol 0.634, 5min_bear_trend 0.626.
   Live prediction layer (timeseries_service.MODEL_CONFIGS) loads ONLY base direction_predictor_{tf}.
3. Dead+collapsed → retire/rebuild: risk_of_ruin (6/6), sector_relative (3/3), exit_timing (weak 0.455), gap_fill (5/5), volatility (7/7, target fixed).

## Shipped this session
- v19.34.311  gate outcome-label normalization (deployed, verified)
- v19.34.311b gate attribution + hygiene reconciler (deployed, 24/24)
- v19.34.312  absolute class-collapse promotion gate (deployed, 3/3) — protects ALL families
- v19.34.312  volatility target rebalance (deployed, 6/6) — 85/15 → ~50/50

## Prioritized fix roadmap (pending user pick)
- P-LIVE-1: ensemble meta-label target fix (class-weight / balanced) — fixes the live +15 layer.
- P-LIVE-2: 2/7 core direction collapsed — retrain under P0 (auto-rejected if still collapsed).
- P-WIRE:   regime-conditional model selection (use gate's classify_regime to pick variant) — biggest signal upgrade, ~18 healthy dead models.
- P-TARGET: gap session-gap redesign (retire daily/weekly); risk_of_ruin + sector_relative fix-or-retire.
- P-RETIRE: exit_timing.
