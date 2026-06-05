# Training-Pipeline Audit — post m5/m7/m8/m9 (2026-06)

**Purpose:** after the m-series taxonomy/execution work (canonical grading m5,
horizon-aware lookback m7, tidal_wave split m8, exit_archetype data-override m9),
determine whether the ML training pipeline needs to **add, adjust, or retrain**
any models — grounded in the actual code, not assumptions.

**Method:** read-only trace of every place the m-series changes can reach a model
input, training label, or model-routing decision. Companion runnable probe:
`backend/scripts/retrain_readiness.py` (per-family staleness, corpus freshness,
new-label sample accrual, and the m7 market_setup flip-rate).

**Headline:** the pipeline is **structurally sound — NO architecture change and
NO new models are required.** The warranted action is a **freshness retrain**
(models predate the entire m-series), and — *only if the probe shows a material
m7 flip-rate* — regenerating the timeseries-GBM `market_setup` labels with the
same horizon-aware lookback used at serve time. Everything else degrades
gracefully (consistent with the m6 finding).

---

## 1. How the pipeline is actually built (the part that determines impact)

- **Supervised models are FAMILY-keyed, not per-raw-setup.**
  `SETUP_TRAINING_PROFILES` + `SETUP_FEATURE_EXTRACTORS` are keyed by FAMILY
  (`MOMENTUM`, `MEAN_REVERSION`, `BREAKOUT`, `SCALP`, `GAP_AND_GO`, `RANGE`,
  `REVERSAL`, `TREND_CONTINUATION`, `ORB`, `VWAP`). Phases: generic_directional(7),
  setup_specific long(17) + short(17), volatility(7), ensembles + CNNs.
- **Training data = price windows + triple-barrier (López de Prado) labels read
  directly from `ib_historical_data`.** Raw scanner `setup_type`
  (`tidal_wave`/`fading_bounce`) is **NOT a training input** — it only routes at
  *inference* via `SCANNER_TO_ENSEMBLE_KEY → family`.
- **One categorical layer DOES enter supervised training:** the timeseries-GBM
  models train on a `market_setup` + multi-index-regime + sector one-hot
  (`composite_label_features.build_label_features`, `timeseries_service.py` L2577)
  and at inference re-derive `market_setup` from the classifier (L3057 / cache
  read L3035).
- **Model store:** Mongo `timeseries_models` (`last_trained`, `training_samples`,
  `accuracy`). Models last trained in the **2026-04** era — i.e. **before m5, m7,
  m8, m9**.

## 2. Per-change impact on training

| Change | Reaches a model how | Verdict | Severity |
|---|---|---|---|
| **m8 — tidal_wave split / fading_bounce** | Inference *routing* only (`TIDAL_WAVE→MOMENTUM`, `FADING_BOUNCE→MEAN_REVERSION`); history migrated. Family-keyed price-window training is name-agnostic. | **No new models, no label corruption.** New genuine momentum `tidal_wave` is scored by the MOMENTUM head (correct). | **LOW** (freshness only) |
| **m9 — exit_archetype override** | Changes bracket geometry → future realized exits. Supervised labels are **triple-barrier from price**, NOT bot exits. | **No impact on supervised training. No feedback loop.** Only touches grade/EV/learning empirical pillars (separate, already canonical via m5). | **NONE** (for models) |
| **m7 — horizon-aware lookback** | `market_setup` one-hot **is** a timeseries-GBM training feature. Models were trained on **30-bar** market_setup labels; now served with **deep-lookback** (120/252/504) labels for swing/position. | **Train/serve skew** on `setup_label_*` for swing/position trades. Magnitude = how often deeper history flips the label → **measure with the probe.** | **LOW–MODERATE** (data-dependent) |
| **m5 — canonical grade/EV** | Feeds TQS score pillar + confidence gate, NOT the XGB/GBM feature vector. | **No model-internal change** (already consistent at serve). | **NONE** (for models) |

## 3. What to do (and when)

1. **Freshness retrain (recommended, sample-gated, not urgent).** Models predate
   the whole m-series and are ~6 weeks stale. A standard trophy retrain on the
   newer corpus refreshes all family heads and lets the genuine momentum
   `tidal_wave` surges enter the MOMENTUM price-window training set. **No config
   change needed** — same `SETUP_TRAINING_PROFILES`. Gate on corpus freshness +
   accrual (probe).
2. **Kill the m7 train/serve skew IFF the probe flip-rate is material (> ~15%).**
   Regenerate the timeseries-GBM `market_setup` training labels using the SAME
   horizon-aware lookback as serve (pass `trade_style` into the classifier when
   building training labels in `timeseries_service.py` ~L2577), then retrain those
   GBMs. If flip-rate is low, no action — the skew is negligible.
3. **No new per-setup models, no new one-hot features.** Per the m6 guardrail,
   never add canonical/family/setup names as a NEW one-hot without a full retrain
   + feature-version bump. The family-keyed design already covers the new labels.
4. **m9 sample accrual is a GRADING/override concern, not a model concern.** The
   exit_archetype override + setup grade/EV need ≥N closed samples per new label
   before they act — the probe tracks this so you know when those pillars (and any
   future retrain that *wants* realized-outcome features) have enough data.

## 4. Retrain-readiness probe — `backend/scripts/retrain_readiness.py`

Read-only. Reports a GO/WAIT per dimension:
- **Model staleness** — per family: model count + newest/oldest `last_trained` age.
- **Corpus freshness** — newest `date` per `bar_size` in `ib_historical_data`.
- **New-label accrual** — closed `bot_trades` (+ `alert_outcomes`) counts for
  canonical `tidal_wave` (momentum) and `fading_bounce` since the m8 migration.
- **m7 flip-rate** — samples symbols with deep daily history, classifies each at
  30-bar vs 252-bar lookback (cache-bypassed), reports % of `market_setup` labels
  that change → the concrete train/serve-skew metric for decision #2.

Run on the DGX:
```
cd ~/Trading-and-Analysis-Platform/backend
python scripts/retrain_readiness.py            # full report
python scripts/retrain_readiness.py --flip-sample 60 --accrual-since 2026-05-01
```

## 5. Bottom line
- **Do we need to add/adjust models or the pipeline?** No structural change, no new
  models. The architecture already absorbs the taxonomy changes.
- **Do we need to retrain?** Yes — a **freshness retrain** (models are pre-m-series),
  plus a **targeted timeseries-GBM relabel+retrain** *only if* the m7 flip-rate
  probe says the skew is material. Both are sample-gated; run the probe to set the
  trigger.
