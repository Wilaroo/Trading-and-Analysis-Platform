# Deep-Dive Audit — Trade-Finding & Trade-Taking Scoring (2026-06, market closed)

Mandate: make a 90/A mean "90/A *for THIS archetype*". TSLA rubberband-scalp-long
and TSLA swing-short may both read 90/A, but each must be derived from its OWN
reasoning, weighting, regime logic, and reliability. Find every data gap,
unreliable feed, and miscalculated input. Get trade-finding + trade-taking
profitable and reliable ASAP.

## 0. VERDICT — how far from the vision

Maturity scorecard (0 = absent, 5 = production-grade):

| Capability                                             | Today | Notes |
|--------------------------------------------------------|:----:|-------|
| Per-style weighting (scalp vs swing)                   | 3/5  | `STYLE_WEIGHTS` exist but are hand-set, not learned |
| Per-direction branching (long vs short)                | 3/5  | exists in every pillar, hand-set thresholds |
| Setup × regime interaction (the real edge)             | 0/5  | regime is a GLOBAL 5×2 matrix; no setup conditioning |
| Sector-regime in the score / on the trade              | 0/5  | computed on alert, NOT persisted, NOT scored |
| Per-symbol relative-strength regime in the score       | 1/5  | RS pillar exists; rs_rating not persisted on trade |
| Outcome-calibrated (scores predict realized R/MFE)     | 0/5  | proven spearman≈0 across all 5 pillars |
| Conditional reliability ("trust this cell" vs not)     | 0/5  | no per-cell sample-size / CI anywhere |
| Self-improving / generalizing                          | 0/5  | nothing is fit to data; static expert system |

Bottom line: the system has the **shape** of conditionality (style weights +
direction branches) but none of the **substance** (regime-conditional,
outcome-calibrated, per-archetype reliability). We are ~20% of the way to the
vision. The current composite is a fixed linear average of mostly-absent inputs;
it mathematically cannot express "for this archetype RSI matters, for that one it
doesn't" beyond 5 coarse style presets, and it is not calibrated to outcomes.

## 1. ARCHITECTURE MAP (finding → taking)

FINDING (scanner): `scoring_engine.py` — hand-tuned points system
(technical/fundamental/catalyst/risk/context), e.g. `alignment_matrix`
(L727-739) and sector-rank bands (L748-763) are hardcoded constants.
→ produces scanner `score` (persisted as `entry_context.score`).

QUALITY (TQS): `tqs/tqs_engine.py` weighted avg of 5 pillars
(setup/technical/fundamental/context/execution). Proven noise vs MFE.

TAKING (gate): `ai_modules/confidence_gate.py` — model-driven `confidence_score`
+ `position_multiplier` + `decision` (GO/REDUCE/SKIP). Proven noise/inverted.

REGIME (3 layers exist, only 1 is wired into the trade record):
- market: `market_regime_engine.get_current_regime().composite_score`
  → stamped as `entry_context.regime_score` (MARKET-WIDE, identical on every
  trade in a scan cycle).
- sector: `sector_regime_classifier.py` (11 SPDR ETFs, 6 buckets) →
  `alert.sector_regime` is set (enhanced_scanner L7343-7359) but **DROPPED** in
  `build_entry_context` — never persisted, never scored.
- symbol RS: `rs_leadership_service` rs_rating (1-99) → used for focus list,
  **not** persisted on the trade, **not** in the TQS context pillar's RS sub
  (that one recomputes its own daily-bar RS).

## 2. WHY THE CURRENT SCORE CAN'T EXPRESS THE VISION (structural)

1. **Fixed linear average** (`tqs_engine` L425-431). No interaction terms. The
   only conditioning is 5 style weight presets + long/short branches. A TSLA
   scalp-long and TSLA swing-short differ ONLY in which fixed weight vector
   multiplies the SAME globally-mapped sub-scores.
2. **Global sub-score maps.** Every threshold (RSI 30-50→90, VIX 15-22→85,
   day Wed→80, opening_drive→95, etc.) is one constant applied to ALL
   symbols/regimes/setups. There is no "RSI 70 means something different for a
   rubberband scalp vs a swing breakout."
3. **Regime is mashed into one 5×2 matrix** (`context_quality` REGIME_SCORES
   L174-182), shared by all setups, derived from a single `spy_change_pct`
   number. The rich `(setup × direction × regime-band)` expectancy that setup-EV
   proves *does* separate outcomes is thrown away here.
4. **Nothing is calibrated to outcomes.** Weights and maps are SMB folklore.
   Per-pillar predictiveness report: all 5 pillars spearman≈0 vs MFE. A score
   uncorrelated with the thing it claims to measure is not "trustable."

## 3. DATA-GAP REGISTRY (the hunt — find all of them)

### A. Absent → neutral-50 masking (variance collapse → noise)
Every pillar defaults missing inputs to 50, so a weighted average of mostly-50s
collapses to p50≈50, sd≈4 → cannot rank-separate trades (the arithmetic root of
spearman≈0). Confirmed sites:
- engine `TQSResult.score=50.0` default (tqs_engine L38); all pillar dataclasses
  default sub-scores to 50.
- technical: `rsi=50, ma_stack=neutral→60, atr=2.0, rvol=1.0, S/R=5%`
  (technical_quality L196-202) when snapshot missing. ma_stack ~78% neutral.
- context: `rs=50` no bars (L620), `sector unknown→rank 6` (L464), `vix=18`
  (L462), `ai=50` default (L584).
- fundamental: `SI=5, float=100M, inst=50%` placeholders (L293-300) then
  re-neutralized to 50 (L473-498); catalyst floored 40 when absent (L350).
- execution: `history pinned 60` (L461-462), tilt 100, entry/exit/streak 50,
  recent_win_rate 0.5.
- setup: `win_rate 0.5`, EV proxy from R:R when no live EV.
SEVERITY: P0. This is the dominant reason TQS is noise.

### B. Hardcoded/folklore tables that are anti-predictive
- context TIME_SCORES (L161-171): `opening_drive momentum=95` but discovery
  shows opening_drive is the WORST window (−0.486R). Table rewards the loser.
- context REGIME_SCORES (L174-182): global, mis-signed vs MFE.
- setup SETUP_BASE_SCORES (L140-175): `opening_drive=80`; `daily_breakout` not
  in map; static SMB tiers proven mildly anti-predictive.
- scoring_engine alignment_matrix (L727-739) + sector bands (L748-763): hand-set
  points, never validated against outcomes.
- context day-of-week (L566-573): Wednesday=80 pure folklore (3% weight).
SEVERITY: P1 (some inverted = actively harmful).

### C. Persistence gaps — the model can't learn what isn't stored
- **sector_regime NOT persisted** to entry_context (computed, then dropped).
- **per-symbol RS regime / rs_rating NOT persisted** on the trade.
- **regime_score is market-wide**, identical across all trades in a cycle → zero
  per-symbol regime granularity in the training data.
- **trigger_price not always persisted** → `trigger_drift` (chase %) coverage is
  partial; the single most intuitive scalp entry-quality metric is half-dark
  (entry_feature_discovery `_trigger_drift` reports best-effort).
- rvol / gap_pct_abs returned None/zero-variance in the n=807 discovery → likely
  coverage/quality gap (DGX-verify).
SEVERITY: P0 for the rebuild (this is the keystone plumbing).

### D. Unreliable upstream feeds (garbage-in)
- gate `confidence_score`: model-driven; models trained on sparse/unreliable
  labels until recently → noise (−0.029); `gate_decision` INVERTED (go −0.178R
  worse than reduce −0.078R). Operator-confirmed cause: immature models + thin
  clean data. → retrain on the clean window once enough labels; until then the
  gate must NOT lean on model-confidence as its backbone.
- learning_loop win_rate/EV: degenerate, pinned ~0.55 for ~95% of book.
- alpaca quote path effectively dead on ib-direct DGX → many context inputs use
  daily-bar fallbacks or defaults; sector via alpaca dead, IB-bar fallback
  covers ~76% (~24% no-data).
SEVERITY: P1.

### E. Miscalculated / mis-signed
- `regime_score` consumed as "higher=better" but empirically inverted (−0.234).
- RSI degenerate cases (RSI=100) flagged earlier — clamp/min-bars guard pending.
- execution tilt can go negative without a [0,100] clamp (earlier flagged).
- execution position-size check hardcodes "~$50/share avg" (execution L566).
SEVERITY: P2 (targeted fixes).

## 4. TARGET ARCHITECTURE — per-archetype conditional Expected-R

Replace "abstract 0-100 quality" with **predicted expected-R (or P(+1R before
−1R)) conditioned on the full context**: archetype = setup_class × direction ×
time_window × regime (market+sector+symbol). This is interpretable
("this setup, this regime, this time → +0.2R expected"), directly tied to the
target, and naturally absorbs all regime layers — and a 90/A then literally
means "top-decile expected-R *for that archetype*", derived from that archetype's
own cells, exactly the vision.

Quant-craft caveat: conditioning explodes combinatorially (thousands of cells,
~1,000 trades). Estimate fine cells directly → overfit (how TQS got here). Fix =
**hierarchical shrinkage / partial pooling** (empirical-Bayes / James-Stein), or
a regularized GBM with monotonic constraints. Start from robust MARGINAL factors,
let regime conditioning sharpen as clean data accrues. Use per-cell sample size /
CI as the explicit RELIABILITY signal (the missing 0/5 capability).

Robust signals to seed it (from discovery, n=1002):
- time_window (down-weight midday/opening_drive/late_morning), direction
  (shorts bleed ~5×), priority (monotonic), timeframe (scalp worst), shrunk
  per-setup EV, re-signed regime_score, + rsi/trigger_probability/tape_score.

## 5. PHASED ROADMAP (shadow/observe-first, per safety doctrine)

PHASE 0 (now, read-only/observe, low-risk — the keystone plumbing):
1. Persist `sector_regime` + per-symbol `rs_rating`/RS-regime onto entry_context
   (classifiers already exist; just stamp them). Start logging immediately so
   Phase 2 has data.
2. Audit feature COVERAGE on closed bot_trades for the robust predictors
   (read-only report).
3. Fix `regime_score` sign/consumption + add a time-of-day edge factor
   (midday/opening_drive/late_morning) in OBSERVE mode (no live behavior change).
4. Persist `trigger_price` reliably → unlock trigger_drift (chase) signal.

PHASE 1: Entry Edge Score v1 = expected-R from robust MARGINAL factors, run in
SHADOW via the existing shadow-arms harness (log what it WOULD gate vs actual).
Promote to gate basis (unifying TQS↔gate) once it shows lift.

PHASE 2: regime-conditional EV with hierarchical shrinkage + retrain gate models
on the clean window. Per-cell CI = reliability.

## 6. OPEN QUESTIONS FOR OPERATOR
- Modeling: shrinkage-table base (transparent) vs GBM (flexible) vs layered?
- Label: expected MFE_R vs P(+1R before −1R) vs realized clean-R?
- Book steer: intraday-in-good-windows + long-bias + small swing ballast?
  (matches stated preference: fast turnover, minimal overnight.)
