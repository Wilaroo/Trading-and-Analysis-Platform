# 🔜 NEXT SESSION — START HERE (forked 2026-06-11)

## ✅ v320 (Tier 1a) + v320b (Tier 1b) BUILT & CONTAINER-TESTED 2026-06 — AWAITING DGX APPLY
- Patchers on paste.rs: CPCV/GBM `mOsoh` · backtest costs `UGzyM` · tests `9ukb3` / `9Ryar`
- Tier 1a: run_gbm_cpcv() in timeseries_gbm.py (15-fold purged CPCV, PBO proxy, env knobs
  TB_GBM_CPCV*), event_intervals threaded through train_vectorized + setup trainer,
  ModelMetrics cpcv_* fields persist to timeseries_models.metrics. ALSO fixed: inline
  train_full_universe path in timeseries_service.py was MISSING the v319b embargo — now embargoed.
- Tier 1b: advanced_backtest_engine.py — next-bar-open fills, adverse slippage (BT_SLIPPAGE_BPS,
  default 2), IBKR commission (BT_COMMISSION_PER_SHARE 0.005 / min 1.00), gap-through stop fills,
  favorable gap target fills. BT_COSTS=0 restores legacy. Costs ON BY DEFAULT → expect lower
  (honest) revalidation numbers.
- Known quirk: span-based purge in purged_cpcv.py empties train for the {first,last} group combo
  → 14 usable folds of 15 (deterministic, conservative). Pinned in tests.
- Pre-existing STALE test failures (NOT v320): test_model_protection_class_collapse (6),
  test_phase3_4_45 (5) — expectations predate v19.34.312 ABS class-collapse gate + newer
  train_full_universe defaults. Confirmed failing on pristine tree. Housekeeping candidate.

Respond in ENGLISH only. This is a physical DGX deployment.

## ⛔ HARD WORKFLOW RULES (do not violate — caused >10 crashes in prior forks)
- DO NOT use `testing_agent`. DO NOT `git commit`/`git push` from the bash tool. These
  crash on the DGX hardware bindings.
- Ship every change as a **`.patch` via git diff OR (preferred for big monolith files) a
  line-number-proof Python string-patcher**, upload to paste.rs (`curl -sS --data-binary
  @file https://paste.rs/`), and give the OPERATOR exact apply commands. The operator runs
  everything on the DGX and pastes results back.
- WHY string-patcher: the container's git tree drifts from the live DGX tree (e.g.
  `timeseries_gbm.py` had class at line 217 here vs 209 on DGX), so context-based git
  patches can fail. The v319b+c patcher (`/tmp/apply_v319bc.py`, paste.rs/GrkS1) is the
  template: anchor on exact strings, idempotent, py_compile before write, dry-run/--commit.
- Validate every patch locally first: pytest (container has numpy/xgboost/pytest) + reverse
  `git apply -R --check`. The container has NO IB/GPU/Mongo, so logic tests use synthetic data.
- Python env on DGX: `../.venv/bin/python` from `backend/` (= `.venv/bin/python` from repo
  root). Prefix `PYTHONPATH=.`. Backend restart: `./start_backend.sh --force` (repo root,
  NOT backend/). Training runs as a fresh subprocess → picks up code from disk, no restart
  needed for training-path changes.

## ✅ STATE AS OF FORK (all committed: DGX main @ d96def40, pushed)
- v319 NO-PEEK gap fix — LIVE + verified; 3 honest gap models promoted (1min 0.750, 5min
  0.689, 15min 0.706); leaky+retired gap daily/weekly evicted.
- v319b embargo (train/val purge, `_embargo_size`, env TB_EMBARGO_BARS) — applied.
- v319c GBM_FORCE_PROMOTE override (`_force_promote_enabled`) — applied.
- v319d Phase-8 ensemble FFD match-fix — applied.
- Full leakage audit (training + validation/backtest) DONE → see
  `/app/memory/PIPELINE_LEAKAGE_AUDIT_2026-06-11.md`. Verdict: gap was the ONLY leak;
  everything else aligned correctly. Backtest has no look-ahead but IS optimistic (see below).

## ⏳ PENDING DGX OPS (operator has NOT run these yet — sequence matters)
- Retired-model eviction (risk_of_ruin ×6, sector_rel ×3): script ready paste.rs/wL0HT
  (`cleanup_retired_models_v319.py`, dry-run/--commit). Dead-at-inference, UI already excludes.
- FULL RETRAIN (`POST /api/ai-training/start {"force_retrain": true}`): **DO THIS AFTER
  Tier 1a so models are validated with CPCV.** Watch for `embargo gap: purging…` and possible
  embargo-driven `NOT promoted` (use GBM_FORCE_PROMOTE if you want those families replaced).
- Standing manual P0: operator must rotate Atlas DB password (old creds in git history).

## 🎯 NEXT TASK = Tier 1a: wire Purged CPCV into the GBM models
WHY: 100+ GBM models (gap/direction/vol/setup/exit — the bulk of live signals) use a SINGLE
embargoed train/val split, and the validation backtest scores them over their own training
history (in-sample at model level → optimistic). A full Combinatorial Purged CV module
ALREADY EXISTS (`services/ai_modules/purged_cpcv.py`) but is only wired to the DL models
(cnn_lstm, TFT, dl_training_utils, model_scorecard). Wiring it into GBM gives, per model: a
distribution of purged+embargoed OOS scores, true OOS, and PBO (probability of backtest
overfit) via `cpcv_stability` — essentially for free.

KEY CODE FACTS:
- `purged_cpcv.py`: `PurgedKFold(event_intervals, n_splits=5, embargo_bars)`,
  `CombinatorialPurgedKFold(event_intervals, n_splits=6, n_test_splits=2, embargo_bars=10)`,
  `cpcv_stability(oos_scores)->dict`. `.split()` yields (train_idx, test_idx).
- `timeseries_gbm.py train_from_features` (~line 1059+): currently single split at ~line 1108
  (now embargoed via `_embargo_size`). `event_intervals` ALREADY computed for
  `concurrency_weights` (~line 1011-1021) — same object feeds the CPCV splitter.
- Integration plan: run CPCV over (X, y, event_intervals) to compute an OOS score
  distribution + PBO; REPORT these in the model metrics/scorecard; keep the production model
  as a final fit on all-data-minus-embargo (CPCV is for HONEST METRICS, not the shipped fit).
  Gate promotion can later use PBO (Tier 3b).
- Add pytest (synthetic) pinning: CPCV produces N folds, no train/test index overlap after
  purge+embargo, cpcv_stability returns sane PBO. Validate in container.
- Deliver as a string-patcher (timeseries_gbm.py is a big drifting monolith).

## THEN (same fork or next): Tier 1b execution costs in backtest
`services/slow_learning/advanced_backtest_engine.py` `_simulate_strategy_with_ai` /
`_simulate_strategy_with_gate`: entries fill at signal-bar close (`entry_price=current_price`,
~line 1376) and exits at EXACT stop/target (no slippage/gap). Add: slippage bps + commission +
next-bar-open fills + gap-through stop fills. Localized change.

## Tier 2 / Tier 3 backlog (after Tier 1, design agreed with user)
- 2a per-model probability calibration (isotonic on held-out CPCV folds) → honest gate EV.
- 2b frozen forward hold-out (recent ~45-60d never trained on) as final promotion sanity gate.
- 3a model/prediction DRIFT monitor (PSI/KS vs training baseline) + auto-retrain trigger + NIA tile.
- 3b promotion gated on PBO < ~0.2 + OOS-Sharpe stability (not just DSR).
- 3c extend P-WIRE shadow eval to ALL model families (today regime-only).

## Validation/backtest caveat to remember
Backtest = no look-ahead but optimistic: (1) in-sample at model level [Tier 1a/2b fix],
(2) frictionless fills [Tier 1b fix]. Trust the embargoed train/val (soon CPCV) numbers, not
the backtest equity curve. Paper trading IS the genuine live OOS test — fine to run in parallel.

## Useful artifacts (paste.rs, may expire — regenerate if 404)
- v319 gap patch hIfcL · v319d FFD U7WVq · v319b+c patcher GrkS1 (tests 8qxvj/fWkS3)
- eviction (gap) KROyI · retired cleanup wL0HT · inventory check agSpf · gap_nopeek_verify (in repo)
