# Full Training-Pipeline Leakage Audit — 2026-06-11 (pre-full-retrain)

Triggered by a yellow flag: `direction_predictor_1min_bull/bear` at 0.783/0.760.
Goal: confirm no leakage beyond the gap bug (v319) before a full retrain.

## Method
Traced feature↔target alignment by reading the code for every family +
shared surfaces (feature engineer, regime label, GBM fit). No testing_agent
(DGX hardware). Read-only.

## Findings — CLEAN (no new leakage)

| Family | Feature window | Target | Verdict |
|---|---|---|---|
| direction (generic / setup / short, Phase 1/2/2.5) | trailing, ends at bar i (`base_matrix[bar_i-49]`, sliding windows ending at i) | triple-barrier outcome over `[i+1, i+max_bars]` (`triple_barrier_label_single` scans `range(entry_idx+1, end+1)`) | ✅ clean |
| regime-conditional (Phase 7) | same as direction + regime label | regime via `classify_regime_for_date` = 25 SPY bars `[start:idx+1]` **ending** at the sample's date (no future) | ✅ clean — 78% is genuine regime conditioning (bull day → up-barrier hits more; regime known at day open) |
| volatility (Phase 3) | trailing, ends at i (`compute_vol_features_batch` lookback=50) | forward vol `vol_all[i]`=returns over `[i,i+fh]` vs trailing vol `vol_all[i-fh]` | ✅ clean — 0.84 is real vol clustering (GARCH); v312 made it fair ~50/50 |
| exit timing (Phase 4) | trailing, ends at entry bar | forward argmax over `[i+1, i+mh]` (`fwd_h[i+1]`) | ✅ clean (acc 0.37–0.55 anyway) |
| gap fill (Phase 5.5) | ends at bar i-1 (no-peek) | `[i+1, i+w]` | ✅ fixed v319 |
| base feature engineer (`extract_features_bulk`) | `idx=arange(lb-1,n)`; all features use `closes[idx], closes[idx-1], closes[idx-3]…` — trailing only, zero forward refs | n/a | ✅ no look-ahead |

Shared surfaces:
- **No full-data feature scaling** — XGBoost (scale-invariant); no StandardScaler/MinMaxScaler fit anywhere. ✅
- **Train/val embargo** — added v319b (López de Prado purge). ✅
- **Ensemble Phase-8 FFD** — fixed v319d (was zero-filling FFD cols). ✅

## Cleanup items (NOT leakage, NOT retrain blockers)
1. Dead-code backward-return target in single `extract_features` (timeseries_features.py
   lines 168-185): mislabels a past return as "future". **Never executed** — every caller
   passes `include_target=False` (verified). Left as-is to avoid churn before retrain;
   delete in a future cleanup.
2. Retired families still in `timeseries_models`: `risk_of_ruin` ×6, `sector_rel` ×3.
   Retired v314, dead-at-inference (only referenced in their own model modules — no
   gate/scanner/inference consumer). Evicted via `/tmp/cleanup_retired_models_v319.py`
   (paste.rs/wL0HT). UI already excludes them (TrainingPipelinePanel ALL_PHASES, v316) →
   NO UI change needed.

## Conclusion
The gap leak (v319) was the only real leakage. All other families are correctly
aligned (features end at i, targets strictly future). High accuracies (vol 0.84,
regime-direction 0.78) are legitimate. **Cleared to evict retired models and run a
full retrain.** Watch the retrain for: `embargo gap: purging…` (v319b live), Phase-8
sub-models getting real FFD (v319d), and any embargo-driven `NOT promoted` (gate may
keep slightly-inflated pre-embargo incumbents → use GBM_FORCE_PROMOTE if you want them
replaced).
