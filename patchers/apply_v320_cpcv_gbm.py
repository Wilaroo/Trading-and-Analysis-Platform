#!/usr/bin/env python3
"""
apply_v320_cpcv_gbm.py — Tier 1a: wire Combinatorial Purged CV (CPCV) into GBM models
======================================================================================

WHAT THIS DOES (v320):
  1. timeseries_gbm.py
     - ModelMetrics gains cpcv_* fields (OOS acc distribution + PBO proxy) —
       persisted automatically to `timeseries_models.metrics` via to_dict().
     - New module-level `run_gbm_cpcv()` + `_cpcv_fallback_intervals()` —
       lightweight purged+embargoed CPCV evaluation (C(6,2)=15 folds default).
     - `train_from_features()` gains optional `event_intervals` param and runs
       CPCV before the final fit. THE SHIPPED MODEL IS UNCHANGED — CPCV exists
       for honest metrics only.
     - `train_vectorized()` builds globally-offset event intervals (cnn_lstm
       convention) and passes them through.
  2. timeseries_service.py
     - Inline full-universe trainer: adds the v319b embargo this path MISSED
       + CPCV metrics for the generic direction predictors.
     - Setup-type trainer: builds exact per-pattern event intervals and passes
       them to train_from_features (CPCV for all setup models).

ENV KNOBS (all optional):
  TB_GBM_CPCV=0              disable CPCV entirely
  TB_GBM_CPCV_SPLITS         N groups (default 6)
  TB_GBM_CPCV_TEST_SPLITS    K held-out groups (default 2 -> C(6,2)=15 folds)
  TB_GBM_CPCV_MAX_ROWS       row cap for fold evals (default 300000)
  TB_GBM_CPCV_BOOST_ROUNDS   boost-round cap for fold fits (default 150)

USAGE (from the repo's backend/ directory, or pass --backend):
  python apply_v320_cpcv_gbm.py            # dry-run (default, writes nothing)
  python apply_v320_cpcv_gbm.py --commit   # apply

Safety: string-anchored (line-number agnostic), idempotent (marker check),
py_compile before write, all-or-nothing per file.
"""
import argparse
import os
import py_compile
import sys
import tempfile

# ════════════════════════════════════════════════════════════════════════════
# New module-level code injected into timeseries_gbm.py
# ════════════════════════════════════════════════════════════════════════════

GBM_CPCV_FUNCS = '''

# ── v320 Tier-1a: Combinatorial Purged CV (CPCV) for GBM models ──────────────
# The GBM families (direction/gap/vol/setup/exit) previously shipped with a
# SINGLE embargoed train/val split, so headline metrics were a one-exam point
# estimate. CPCV re-trains LIGHTWEIGHT fold models over C(n_splits,
# n_test_splits) purged+embargoed train/test combinations to produce an OOS
# score DISTRIBUTION plus a PBO proxy. The production model is NOT changed —
# CPCV exists for honest metrics, not for the shipped fit.
#
# Env knobs:
#   TB_GBM_CPCV=0              -> disable entirely
#   TB_GBM_CPCV_SPLITS         -> N groups (default 6)
#   TB_GBM_CPCV_TEST_SPLITS    -> K held-out groups (default 2 -> C(6,2)=15)
#   TB_GBM_CPCV_MAX_ROWS       -> row cap per fold-eval (default 300000)
#   TB_GBM_CPCV_BOOST_ROUNDS   -> boost-round cap for fold fits (default 150)

_CPCV_ZERO = {
    "cpcv_n_folds": 0, "cpcv_oos_acc_mean": 0.0, "cpcv_oos_acc_std": 0.0,
    "cpcv_oos_acc_p05": 0.0, "cpcv_oos_acc_min": 0.0,
    "cpcv_edge_mean": 0.0, "cpcv_pbo": 0.0,
}


def _cpcv_fallback_intervals(n_samples: int, forecast_horizon: int) -> np.ndarray:
    """Conservative event intervals when the caller has none: treat samples as
    CONSECUTIVE bars whose labels look `forecast_horizon` bars forward. Within
    a symbol block this is exactly right; at block boundaries it over-purges a
    few extra samples (conservative — never optimistic)."""
    fh = max(1, int(forecast_horizon))
    idx = np.arange(int(n_samples), dtype=np.int64)
    return np.stack([idx, idx + fh], axis=1)


def run_gbm_cpcv(
    X,
    y,
    sample_weights,
    event_intervals,
    train_params: Dict,
    num_boost_round: int = 300,
    num_classes: int = 3,
    forecast_horizon: int = 5,
    model_name: str = "",
) -> Dict[str, Any]:
    """Purged CPCV OOS evaluation for an XGBoost classifier.

    Returns the cpcv_* metric dict (zeroed when skipped/disabled).
    PBO proxy = fraction of OOS folds whose accuracy does NOT beat that
    fold's majority-class baseline (i.e. no real edge on unseen data).
    Lower is better: < 0.2 healthy, > 0.5 suspicious.
    """
    if str(os.environ.get("TB_GBM_CPCV", "1")).strip().lower() in ("0", "false", "off", "no"):
        return dict(_CPCV_ZERO)
    try:
        n_splits = int(os.environ.get("TB_GBM_CPCV_SPLITS", "6"))
        n_test_splits = int(os.environ.get("TB_GBM_CPCV_TEST_SPLITS", "2"))
        max_rows = int(os.environ.get("TB_GBM_CPCV_MAX_ROWS", "300000"))
        cap_rounds = int(os.environ.get("TB_GBM_CPCV_BOOST_ROUNDS", "150"))
    except (TypeError, ValueError):
        n_splits, n_test_splits, max_rows, cap_rounds = 6, 2, 300000, 150

    try:
        n = len(X)
        if n < n_splits * 50:
            return dict(_CPCV_ZERO)

        if event_intervals is None or len(event_intervals) != n:
            iv = _cpcv_fallback_intervals(n, forecast_horizon)
        else:
            iv = np.asarray(event_intervals, dtype=np.int64)

        w = None
        if sample_weights is not None and len(sample_weights) == n:
            w = np.asarray(sample_weights, dtype=np.float32)

        X_c, y_c = X, np.asarray(y, dtype=np.int64)
        if n > max_rows:
            rng = np.random.default_rng(42)
            keep = np.sort(rng.choice(n, size=max_rows, replace=False))
            X_c, y_c, iv = X_c[keep], y_c[keep], iv[keep]
            if w is not None:
                w = w[keep]

        from services.ai_modules.purged_cpcv import CombinatorialPurgedKFold, cpcv_stability

        embargo = max(1, int(forecast_horizon))
        splitter = CombinatorialPurgedKFold(
            iv, n_splits=n_splits, n_test_splits=n_test_splits, embargo_bars=embargo,
        )
        rounds = max(20, min(int(num_boost_round), cap_rounds))

        accs, edges = [], []
        for fold_i, (tr, te) in enumerate(splitter.split()):
            if len(tr) < 50 or len(te) < 20:
                continue
            try:
                dtr = xgb.DMatrix(X_c[tr], label=y_c[tr], weight=(w[tr] if w is not None else None))
                dte = xgb.DMatrix(X_c[te])
                booster = xgb.train(dict(train_params), dtr, num_boost_round=rounds, verbose_eval=False)
                raw = booster.predict(dte)
                if raw.ndim > 1:
                    pred = np.argmax(raw, axis=1)
                else:
                    pred = (raw > 0.5).astype(np.int64)
                y_te = y_c[te]
                acc = float(np.mean(pred == y_te))
                counts = np.bincount(y_te, minlength=max(2, int(num_classes)))
                baseline = float(counts.max()) / float(max(1, len(y_te)))
                accs.append(acc)
                edges.append(acc - baseline)
            except Exception as fold_err:
                logger.warning(f"[CPCV] {model_name} fold {fold_i} failed: {fold_err}")

        if not accs:
            return dict(_CPCV_ZERO)

        stab = cpcv_stability(accs)
        edge_arr = np.asarray(edges, dtype=np.float64)
        pbo = float((edge_arr <= 0).sum()) / float(len(edge_arr))
        res = {
            "cpcv_n_folds": int(len(accs)),
            "cpcv_oos_acc_mean": float(stab["mean"]),
            "cpcv_oos_acc_std": float(stab["std"]),
            "cpcv_oos_acc_p05": float(stab["p05"]),
            "cpcv_oos_acc_min": float(stab["min"]),
            "cpcv_edge_mean": float(edge_arr.mean()),
            "cpcv_pbo": pbo,
        }
        logger.info(
            f"[CPCV] {model_name}: {res['cpcv_n_folds']} folds · "
            f"OOS acc {res['cpcv_oos_acc_mean']:.3f}±{res['cpcv_oos_acc_std']:.3f} "
            f"(min {res['cpcv_oos_acc_min']:.3f} · p05 {res['cpcv_oos_acc_p05']:.3f}) · "
            f"edge vs baseline {res['cpcv_edge_mean']:+.3f} · PBO {pbo:.2f}"
        )
        return res
    except Exception as cpcv_err:
        logger.warning(f"[CPCV] {model_name} skipped (error: {cpcv_err})")
        return dict(_CPCV_ZERO)
'''

# ════════════════════════════════════════════════════════════════════════════
# EDITS
# ════════════════════════════════════════════════════════════════════════════

EDITS = [
    # ───────────────────────── timeseries_gbm.py ─────────────────────────
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G1: ModelMetrics cpcv_* fields",
        "marker": "cpcv_pbo: float = 0.0",
        "old": """    # Sample info
    training_samples: int = 0
    validation_samples: int = 0""",
        "new": """    # Sample info
    training_samples: int = 0
    validation_samples: int = 0

    # v320 Tier-1a — CPCV (Combinatorial Purged Cross-Validation) honest OOS
    # metrics. cpcv_n_folds == 0 means CPCV was skipped (disabled or not
    # enough data). cpcv_pbo = fraction of OOS folds with NO edge over the
    # majority-class baseline — a probability-of-backtest-overfit proxy
    # (lower is better; < 0.2 healthy, > 0.5 suspicious).
    cpcv_n_folds: int = 0
    cpcv_oos_acc_mean: float = 0.0
    cpcv_oos_acc_std: float = 0.0
    cpcv_oos_acc_p05: float = 0.0
    cpcv_oos_acc_min: float = 0.0
    cpcv_edge_mean: float = 0.0
    cpcv_pbo: float = 0.0""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G2: module-level run_gbm_cpcv()",
        "marker": "def run_gbm_cpcv(",
        "old": """    embargo = min(embargo, split_idx - 1, int(split_idx * 0.25))
    return max(0, embargo)""",
        "new": """    embargo = min(embargo, split_idx - 1, int(split_idx * 0.25))
    return max(0, embargo)

""" + GBM_CPCV_FUNCS.strip("\n"),
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G3: train_from_features event_intervals param",
        "marker": "event_intervals: Optional[np.ndarray] = None,\n    ) -> 'ModelMetrics':",
        "old": """        sample_weights: Optional[np.ndarray] = None,
        apply_class_balance: bool = True,
    ) -> 'ModelMetrics':""",
        "new": """        sample_weights: Optional[np.ndarray] = None,
        apply_class_balance: bool = True,
        event_intervals: Optional[np.ndarray] = None,
    ) -> 'ModelMetrics':""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G4: CPCV evaluation in train_from_features",
        "marker": "_cpcv_res = run_gbm_cpcv(",
        "old": """        # Split train/validation (time-ordered) with a LÓPEZ DE PRADO EMBARGO gap.""",
        "new": """        # ── v320 Tier-1a: CPCV honest OOS evaluation (metrics only) ─────────
        # Runs a CombinatorialPurgedKFold over (X, y) to produce an OOS score
        # distribution + PBO proxy. The SHIPPED model below is still the final
        # fit on all-data-minus-embargo — CPCV is for honest metrics only.
        _cpcv_res = run_gbm_cpcv(
            X, y, sample_weights, event_intervals, train_params,
            num_boost_round=num_boost_round, num_classes=num_classes,
            forecast_horizon=self.forecast_horizon, model_name=self.model_name,
        )

        # Split train/validation (time-ordered) with a LÓPEZ DE PRADO EMBARGO gap.""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G5: ModelMetrics ctor cpcv kwargs",
        "marker": "cpcv_pbo=float(_cpcv_res.get(",
        "old": """            training_samples=len(X_train),
            validation_samples=len(X_val),
            top_features=top_features,""",
        "new": """            training_samples=len(X_train),
            validation_samples=len(X_val),
            cpcv_n_folds=int(_cpcv_res.get("cpcv_n_folds", 0)),
            cpcv_oos_acc_mean=float(_cpcv_res.get("cpcv_oos_acc_mean", 0.0)),
            cpcv_oos_acc_std=float(_cpcv_res.get("cpcv_oos_acc_std", 0.0)),
            cpcv_oos_acc_p05=float(_cpcv_res.get("cpcv_oos_acc_p05", 0.0)),
            cpcv_oos_acc_min=float(_cpcv_res.get("cpcv_oos_acc_min", 0.0)),
            cpcv_edge_mean=float(_cpcv_res.get("cpcv_edge_mean", 0.0)),
            cpcv_pbo=float(_cpcv_res.get("cpcv_pbo", 0.0)),
            top_features=top_features,""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G6a: train_vectorized global-offset intervals",
        "marker": "intervals_parts = []",
        "old": """        # Compute per-symbol uniqueness weights, then concatenate in same order as X
        from .event_intervals import concurrency_weights
        weights_parts = []
        for feat_matrix, iv in zip(all_features, all_intervals_per_symbol):
            n = len(feat_matrix)
            if iv is None or len(iv) == 0:
                weights_parts.append(np.ones(n, dtype=np.float32))
                continue
            # Per-symbol scope: n_bars = max exit + 1
            n_bars = int(iv[:, 1].max()) + 2
            w = concurrency_weights(iv, n_bars=n_bars)
            # Align length to feature matrix
            if len(w) != n:
                w = np.ones(n, dtype=np.float32)
            weights_parts.append(w)
        sample_weights = np.concatenate(weights_parts) if weights_parts else None""",
        "new": """        # Compute per-symbol uniqueness weights, then concatenate in same order as X.
        # v320: ALSO build a single globally-offset event_intervals array (same
        # convention as cnn_lstm: local intervals + cumulative bar offset) so the
        # CPCV splitter in train_from_features can purge across symbol blocks.
        from .event_intervals import concurrency_weights
        weights_parts = []
        intervals_parts = []
        _iv_offset = 0
        _fh = max(1, int(self.forecast_horizon))
        for feat_matrix, iv in zip(all_features, all_intervals_per_symbol):
            n = len(feat_matrix)
            if iv is None or len(iv) == 0:
                weights_parts.append(np.ones(n, dtype=np.float32))
                # Synthesize consecutive-bar intervals so CPCV alignment
                # survives backward-compat 2-tuple worker results.
                if n > 0:
                    ent = np.arange(n, dtype=np.int64)
                    synth = np.stack([ent, ent + _fh], axis=1)
                    intervals_parts.append(synth + _iv_offset)
                    _iv_offset += int(synth[:, 1].max()) + 2
                continue
            # Per-symbol scope: n_bars = max exit + 1
            n_bars = int(iv[:, 1].max()) + 2
            w = concurrency_weights(iv, n_bars=n_bars)
            # Align length to feature matrix
            if len(w) != n:
                w = np.ones(n, dtype=np.float32)
            weights_parts.append(w)
            if len(iv) == n:
                intervals_parts.append(np.asarray(iv, dtype=np.int64) + _iv_offset)
            elif n > 0:
                ent = np.arange(n, dtype=np.int64)
                intervals_parts.append(np.stack([ent, ent + _fh], axis=1) + _iv_offset)
            _iv_offset += n_bars
        sample_weights = np.concatenate(weights_parts) if weights_parts else None
        event_intervals = np.concatenate(intervals_parts) if intervals_parts else None
        if event_intervals is not None and len(event_intervals) != len(X):
            logger.warning(
                f"event_intervals length {len(event_intervals)} != X length {len(X)} — "
                "dropping explicit intervals (CPCV falls back to conservative ones)"
            )
            event_intervals = None""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G6b: del intervals_parts",
        "marker": "del all_features, all_targets, all_intervals_per_symbol, weights_parts, intervals_parts",
        "old": """        del all_features, all_targets, all_intervals_per_symbol, weights_parts""",
        "new": """        del all_features, all_targets, all_intervals_per_symbol, weights_parts, intervals_parts""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G7: valid_rows mask on intervals",
        "marker": "event_intervals = event_intervals[valid_rows]",
        "old": """        valid_rows = np.any(X != 0, axis=1)
        X = X[valid_rows]
        y = y[valid_rows]
        if sample_weights is not None:
            sample_weights = sample_weights[valid_rows]""",
        "new": """        valid_rows = np.any(X != 0, axis=1)
        X = X[valid_rows]
        y = y[valid_rows]
        if sample_weights is not None:
            sample_weights = sample_weights[valid_rows]
        if event_intervals is not None:
            event_intervals = event_intervals[valid_rows]""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "G8: train_vectorized passes event_intervals",
        "marker": "sample_weights=sample_weights,\n            event_intervals=event_intervals,",
        "old": """        return self.train_from_features(
            X, y, feature_names,
            validation_split=0.2,
            num_boost_round=num_boost_round,
            early_stopping_rounds=early_stopping_rounds,
            num_classes=3,
            sample_weights=sample_weights,
        )""",
        "new": """        return self.train_from_features(
            X, y, feature_names,
            validation_split=0.2,
            num_boost_round=num_boost_round,
            early_stopping_rounds=early_stopping_rounds,
            num_classes=3,
            sample_weights=sample_weights,
            event_intervals=event_intervals,
        )""",
    },
    # ──────────────────────── timeseries_service.py ───────────────────────
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S1: embargo for inline full-universe split (v319b gap)",
        "marker": "_emb_size(split_idx",
        "old": """            # Train/validation split
            validation_split = 0.2
            split_idx = int(len(X) * (1 - validation_split))
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]""",
        "new": """            # Train/validation split — v320: embargoed (López de Prado). This
            # inline path previously MISSED the v319b embargo applied to
            # TimeSeriesGBM.train_from_features: the last `horizon` training
            # samples have label windows overlapping the validation block.
            validation_split = 0.2
            split_idx = int(len(X) * (1 - validation_split))
            from .timeseries_gbm import _embargo_size as _emb_size
            _emb = _emb_size(split_idx, int(forecast_horizon), os.environ.get("TB_EMBARGO_BARS"))
            _train_end = split_idx - _emb
            if _emb > 0:
                logger.info(
                    f"[FULL UNIVERSE] embargo gap: purging {_emb} boundary "
                    f"sample(s) — train[:{_train_end}] | val[{split_idx}:] "
                    f"(horizon={forecast_horizon})"
                )
            X_train, X_val = X[:_train_end], X[split_idx:]
            y_train, y_val = y[:_train_end], y[split_idx:]""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S2: CPCV for inline full-universe trainer",
        "marker": "_cpcv_res = run_gbm_cpcv(",
        "old": """            # Save model — mark as 3-class triple-barrier so metadata persists correctly.""",
        "new": """            # ── v320 Tier-1a: CPCV honest OOS evaluation (metrics only) ─────
            # Purged+embargoed OOS distribution + PBO proxy for the generic
            # direction predictor. The shipped model below is unchanged.
            from .timeseries_gbm import run_gbm_cpcv
            try:
                _cpcv_w = compute_per_sample_class_weights(
                    y.astype(np.int64), num_classes=3, clip_ratio=5.0,
                    scheme=get_class_weight_scheme(),
                )
            except Exception:
                _cpcv_w = None
            _cpcv_res = run_gbm_cpcv(
                X, y, _cpcv_w, None, xgb_params,
                num_boost_round=300, num_classes=3,
                forecast_horizon=int(forecast_horizon), model_name=model_name,
            )

            # Save model — mark as 3-class triple-barrier so metadata persists correctly.""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S3: ModelMetrics ctor cpcv kwargs (inline path)",
        "marker": "cpcv_pbo=float(_cpcv_res.get(",
        "old": """                training_samples=len(X_train),
                validation_samples=len(X_val),
                last_trained=datetime.now(timezone.utc).isoformat()
            )""",
        "new": """                training_samples=len(X_train),
                validation_samples=len(X_val),
                cpcv_n_folds=int(_cpcv_res.get("cpcv_n_folds", 0)),
                cpcv_oos_acc_mean=float(_cpcv_res.get("cpcv_oos_acc_mean", 0.0)),
                cpcv_oos_acc_std=float(_cpcv_res.get("cpcv_oos_acc_std", 0.0)),
                cpcv_oos_acc_p05=float(_cpcv_res.get("cpcv_oos_acc_p05", 0.0)),
                cpcv_oos_acc_min=float(_cpcv_res.get("cpcv_oos_acc_min", 0.0)),
                cpcv_edge_mean=float(_cpcv_res.get("cpcv_edge_mean", 0.0)),
                cpcv_pbo=float(_cpcv_res.get("cpcv_pbo", 0.0)),
                last_trained=datetime.now(timezone.utc).isoformat()
            )""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S4: cpcv in train_full_universe return payload",
        "marker": "\"cpcv\": _cpcv_res,",
        "old": """                "training_samples": len(X_train),
                "validation_samples": len(X_val),
                "symbols_processed": symbols_with_data,""",
        "new": """                "training_samples": len(X_train),
                "validation_samples": len(X_val),
                "cpcv": _cpcv_res,
                "symbols_processed": symbols_with_data,""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S5: setup trainer interval accumulators",
        "marker": "all_event_intervals = []",
        "old": """            all_feature_chunks = []
            all_target_list = []
            total_samples = 0
            total_bars_scanned = 0""",
        "new": """            all_feature_chunks = []
            all_target_list = []
            all_event_intervals = []  # v320: (entry, exit) per sample, global bar offset
            _iv_offset = 0
            total_samples = 0
            total_bars_scanned = 0""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S6a: setup trainer interval per sample",
        "marker": "all_event_intervals.append(",
        "old": """                    all_feature_chunks.append(combined)
                    all_target_list.append(target)
                    total_samples += 1""",
        "new": """                    all_feature_chunks.append(combined)
                    all_target_list.append(target)
                    all_event_intervals.append(
                        (_iv_offset + i + 49, _iv_offset + i + 49 + forecast_horizon)
                    )
                    total_samples += 1""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S6b: setup trainer offset advance",
        "marker": "_iv_offset += len(bars)",
        "old": """                del bulk_features, bars, symbol_matches""",
        "new": """                _iv_offset += len(bars)
                del bulk_features, bars, symbol_matches""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "S7: setup trainer passes event_intervals",
        "marker": "event_intervals=_setup_iv,",
        "old": """            metrics = model.train_from_features(
                X, y, combined_feature_names,
                skip_save=True,
                num_boost_round=num_boost_round,
                num_classes=num_classes
            )""",
        "new": """            _setup_iv = (
                np.asarray(all_event_intervals, dtype=np.int64)
                if (all_event_intervals and len(all_event_intervals) == len(X))
                else None
            )
            metrics = model.train_from_features(
                X, y, combined_feature_names,
                skip_save=True,
                num_boost_round=num_boost_round,
                num_classes=num_classes,
                event_intervals=_setup_iv,
            )""",
    },
]


# ════════════════════════════════════════════════════════════════════════════
# Patch engine (string-anchored, idempotent, py_compile-guarded)
# ════════════════════════════════════════════════════════════════════════════

def find_backend(cli_backend):
    if cli_backend:
        return os.path.abspath(cli_backend)
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, "services", "ai_modules")):
        return cwd
    if os.path.isdir(os.path.join(cwd, "backend", "services", "ai_modules")):
        return os.path.join(cwd, "backend")
    print("✗ Could not locate backend dir. Run from repo root or backend/, or pass --backend PATH")
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--backend", default=None, help="path to backend/ directory")
    args = ap.parse_args()

    backend = find_backend(args.backend)
    print(f"Backend dir : {backend}")
    print(f"Mode        : {'COMMIT' if args.commit else 'DRY-RUN (no writes)'}")
    print("-" * 72)

    by_file = {}
    for e in EDITS:
        by_file.setdefault(e["file"], []).append(e)

    all_ok = True
    for rel, edits in by_file.items():
        path = os.path.join(backend, rel)
        if not os.path.exists(path):
            print(f"✗ MISSING FILE: {path}")
            all_ok = False
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        orig = content
        file_ok = True
        applied = 0
        for e in edits:
            if e["marker"] in content:
                print(f"  = skip (already applied): {e['name']}")
                continue
            cnt = content.count(e["old"])
            if cnt != 1:
                print(f"  ✗ anchor found x{cnt} (need exactly 1): {e['name']}")
                file_ok = False
                continue
            content = content.replace(e["old"], e["new"])
            applied += 1
            print(f"  ✓ patched: {e['name']}")

        if not file_ok:
            print(f"✗ {rel}: anchor failure — NOT writing this file")
            all_ok = False
            continue
        if content == orig:
            print(f"= {rel}: nothing to do")
            continue

        # compile-check the patched content before any write
        tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        try:
            py_compile.compile(tmp.name, doraise=True)
        except py_compile.PyCompileError as err:
            print(f"✗ {rel}: COMPILE FAILED after patch — NOT writing\n{err}")
            all_ok = False
            continue
        finally:
            os.unlink(tmp.name)

        if args.commit:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"→ WROTE {rel} ({applied} edits)")
        else:
            print(f"→ DRY-RUN OK for {rel} ({applied} edits would be applied)")

    print("-" * 72)
    if all_ok:
        print("ALL OK." + ("" if args.commit else " Re-run with --commit to apply."))
        sys.exit(0)
    print("FAILURES — see above. Nothing partially written per-file.")
    sys.exit(1)


if __name__ == "__main__":
    main()
