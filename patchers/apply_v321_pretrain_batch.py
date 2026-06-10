#!/usr/bin/env python3
"""
apply_v321_pretrain_batch.py — pre-retrain batch: Tier 2b + 3b(shadow) + 3a-lite
=================================================================================

PREREQUISITES (must already be applied / present):
  * v320 patcher (paste.rs/mOsoh) — this patcher anchors on v320 code.
  * NEW module files downloaded first:
      services/ai_modules/frozen_holdout.py
      services/ai_modules/feature_baseline.py

WHAT THIS DOES:
  Tier 2b — FROZEN FORWARD HOLD-OUT (TB_FROZEN_HOLDOUT_DAYS, default 45):
    * All GBM TRAINING bar loaders drop bars newer than the cutoff:
        - timeseries_service._get_historical_bars_from_db (train/universe/setup paths)
        - training_pipeline.load_symbol_bars (NVMe-cached loader, all 9 families)
        - scripts/local_train.py (standalone trainer)
    * NVMe bar/feature cache filenames + Mongo feature-cache keys embed the
      cutoff -> caches auto-invalidate when the hold-out changes.
    * Model docs are stamped with {"frozen_holdout": {days, cutoff}}.
    * Inference paths untouched — they keep seeing the latest bars.

  Tier 3b — PBO PROMOTION GATE (TB_PBO_GATE = off|shadow|enforce, default shadow):
    * pbo_gate_check() in timeseries_gbm; wired into _save_model AFTER the
      class-collapse gate. Shadow mode logs "[PBO-GATE shadow] WOULD BLOCK …"
      and stamps the archive doc; enforce mode actually refuses promotion
      (returns rejected_pbo_gate; GBM_FORCE_PROMOTE still overrides).
    * Thresholds: TB_PBO_MAX (default 0.20), TB_CPCV_MIN_EDGE (default 0.0).
    * Setup-type models: shadow logging only this round.

  Tier 3a-lite — FEATURE BASELINES (TB_FEATURE_BASELINE, default on):
    * compute_feature_baseline() captures per-feature decile stats at train
      time; persisted in model docs ("feature_baseline") for the future
      drift monitor.

USAGE (from the repo's backend/ directory, or pass --backend):
  python apply_v321_pretrain_batch.py            # dry-run
  python apply_v321_pretrain_batch.py --commit   # apply

Safety: string-anchored (line-number agnostic), idempotent, py_compile before
write, all-or-nothing per file.
"""
import argparse
import os
import py_compile
import sys
import tempfile

PBO_GATE_FUNC = '''

# ── v321 Tier-3b: PBO promotion gate ─────────────────────────────────────────
def pbo_gate_check(metrics_dict: Dict, model_name: str = "") -> tuple:
    """Judge a candidate model's CPCV honesty metrics before promotion.

    Modes via TB_PBO_GATE: "off" | "shadow" (default) | "enforce".
    Thresholds: TB_PBO_MAX (default 0.20), TB_CPCV_MIN_EDGE (default 0.0).

    Returns (verdict, reason) with verdict in {"pass", "shadow_block", "block"}.
    Models WITHOUT CPCV results (cpcv_n_folds == 0) always pass — there is
    nothing to judge (e.g. CPCV disabled or tiny datasets).
    """
    mode = str(os.environ.get("TB_PBO_GATE", "shadow")).strip().lower()
    if mode in ("off", "0", "false", "no"):
        return ("pass", "gate off")
    try:
        pbo_max = float(os.environ.get("TB_PBO_MAX", "0.20"))
        min_edge = float(os.environ.get("TB_CPCV_MIN_EDGE", "0.0"))
    except (TypeError, ValueError):
        pbo_max, min_edge = 0.20, 0.0
    n_folds = int(metrics_dict.get("cpcv_n_folds", 0) or 0)
    if n_folds <= 0:
        return ("pass", "no CPCV data")
    pbo = float(metrics_dict.get("cpcv_pbo", 0.0))
    edge = float(metrics_dict.get("cpcv_edge_mean", 0.0))
    fails = []
    if pbo > pbo_max:
        fails.append(f"PBO {pbo:.2f} > {pbo_max:.2f}")
    if edge <= min_edge:
        fails.append(f"OOS edge {edge:+.3f} <= {min_edge:+.3f}")
    if not fails:
        return ("pass", f"PBO {pbo:.2f}, edge {edge:+.3f} ({n_folds} folds)")
    reason = " & ".join(fails)
    if mode == "enforce":
        return ("block", reason)
    return ("shadow_block", reason)
'''

PBO_GATE_WIRING = '''
            # ── v321 Tier-3b: PBO promotion gate (shadow by default) ────────
            # Judges the CPCV honesty metrics (v320). Shadow mode only LOGS
            # what it would do; TB_PBO_GATE=enforce activates real blocking.
            _pbo_verdict, _pbo_reason = pbo_gate_check(_nm_abs, self.model_name)
            if _pbo_verdict == "shadow_block":
                logger.warning(
                    f"[PBO-GATE shadow] WOULD BLOCK promotion of {self.model_name} "
                    f"{self._version}: {_pbo_reason}. (set TB_PBO_GATE=enforce to activate)"
                )
                try:
                    self._db[self.MODEL_ARCHIVE_COLLECTION].update_one(
                        {"name": self.model_name, "version": self._version},
                        {"$set": {"pbo_gate": {"verdict": "shadow_block", "reason": _pbo_reason}}},
                    )
                except Exception:
                    pass
            elif _pbo_verdict == "block":
                if _force_promote_enabled(self.model_name, os.environ.get("GBM_FORCE_PROMOTE")):
                    logger.warning(
                        f"[PBO-GATE] OVERRIDE (GBM_FORCE_PROMOTE): {self.model_name} "
                        f"{self._version} fails the gate ({_pbo_reason}) but the operator "
                        f"forced promotion."
                    )
                else:
                    logger.warning(
                        f"[PBO-GATE] REJECTED {self.model_name} {self._version}: "
                        f"{_pbo_reason}. NOT promoted; archived as rejected_pbo_gate."
                    )
                    try:
                        self._db[self.MODEL_ARCHIVE_COLLECTION].update_one(
                            {"name": self.model_name, "version": self._version},
                            {"$set": {
                                "rejected_reason": "pbo_gate",
                                "pbo_gate": {"verdict": "block", "reason": _pbo_reason},
                            }},
                        )
                    except Exception:
                        pass
                    if current_active is not None:
                        self._load_model()
                    return "rejected_pbo_gate"
'''

EDITS = [
    # ───────────────────────── timeseries_gbm.py ─────────────────────────
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "V1: pbo_gate_check() module function",
        "marker": "def pbo_gate_check(",
        "old": """    except Exception as cpcv_err:
        logger.warning(f"[CPCV] {model_name} skipped (error: {cpcv_err})")
        return dict(_CPCV_ZERO)""",
        "new": """    except Exception as cpcv_err:
        logger.warning(f"[CPCV] {model_name} skipped (error: {cpcv_err})")
        return dict(_CPCV_ZERO)

""" + PBO_GATE_FUNC.strip("\n"),
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "V2: feature-baseline capture in train_from_features",
        "marker": "self._feature_baseline = compute_feature_baseline(",
        "old": """        _cpcv_res = run_gbm_cpcv(
            X, y, sample_weights, event_intervals, train_params,
            num_boost_round=num_boost_round, num_classes=num_classes,
            forecast_horizon=self.forecast_horizon, model_name=self.model_name,
        )""",
        "new": """        _cpcv_res = run_gbm_cpcv(
            X, y, sample_weights, event_intervals, train_params,
            num_boost_round=num_boost_round, num_classes=num_classes,
            forecast_horizon=self.forecast_horizon, model_name=self.model_name,
        )

        # ── v321 Tier-3a-lite: capture training feature distribution ────────
        # Persisted into the model doc; consumed by the future drift monitor.
        try:
            from services.ai_modules.feature_baseline import compute_feature_baseline
            self._feature_baseline = compute_feature_baseline(X, feature_names)
        except Exception as _fb_err:
            logger.debug(f"feature baseline capture skipped: {_fb_err}")
            self._feature_baseline = None""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "V3: model_doc gains feature_baseline + frozen_holdout stamps",
        "marker": "\"frozen_holdout\": _fh_stamp(),",
        "old": """                "forecast_horizon": self.forecast_horizon,
                "saved_at": datetime.now(timezone.utc).isoformat()
            }""",
        "new": """                "forecast_horizon": self.forecast_horizon,
                "feature_baseline": getattr(self, "_feature_baseline", None),
                "frozen_holdout": _fh_stamp(),
                "saved_at": datetime.now(timezone.utc).isoformat()
            }""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "V3b: frozen_holdout stamp import in _save_model",
        "marker": "from services.ai_modules.frozen_holdout import frozen_holdout_stamp as _fh_stamp",
        "old": """            new_accuracy = self._metrics.accuracy if self._metrics else 0""",
        "new": """            new_accuracy = self._metrics.accuracy if self._metrics else 0
            from services.ai_modules.frozen_holdout import frozen_holdout_stamp as _fh_stamp""",
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "V4: PBO gate wired into _save_model",
        "marker": "_pbo_verdict, _pbo_reason = pbo_gate_check(",
        "old": """                return "rejected_class_collapse"
""",
        "new": """                return "rejected_class_collapse"
""" + PBO_GATE_WIRING,
    },
    {
        "file": "services/ai_modules/timeseries_gbm.py",
        "name": "V5: Mongo feature-cache key embeds hold-out cutoff",
        "marker": "_tb3c_{ffd}_fh{",
        "old": """        ffd = "ffd1" if _os.environ.get("TB_USE_FFD_FEATURES", "0") == "1" else "ffd0"
        return f"{symbol}_{bar_size}_{self.forecast_horizon}_tb3c_{ffd}\"""",
        "new": """        ffd = "ffd1" if _os.environ.get("TB_USE_FFD_FEATURES", "0") == "1" else "ffd0"
        # v321: embed the frozen-holdout setting so changing it invalidates
        # cached features that were extracted from differently-truncated bars.
        from services.ai_modules.frozen_holdout import holdout_days as _hd
        return f"{symbol}_{bar_size}_{self.forecast_horizon}_tb3c_{ffd}_fh{_hd()}\"""",
    },
    # ──────────────────────── timeseries_service.py ───────────────────────
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "V6: frozen hold-out in _get_historical_bars_from_db (training loader)",
        "marker": "bars = apply_frozen_holdout(bars, symbol, bar_size)",
        "old": """                # Convert 'date' field to 'timestamp' for compatibility with model
                for bar in bars:
                    bar['timestamp'] = bar.pop('date', None)""",
        "new": """                # Convert 'date' field to 'timestamp' for compatibility with model
                for bar in bars:
                    bar['timestamp'] = bar.pop('date', None)

                # v321 Tier-2b: FROZEN FORWARD HOLD-OUT. This loader feeds
                # TRAINING paths only (train/universe/setup) — drop bars newer
                # than the cutoff so models never train on the final-exam
                # window. Inference uses different loaders.
                from services.ai_modules.frozen_holdout import apply_frozen_holdout
                bars = apply_frozen_holdout(bars, symbol, bar_size)""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "V7: setup-model doc gains baseline + holdout stamps",
        "marker": "\"frozen_holdout\": _setup_fh_stamp(),",
        "old": """            "feature_names": feature_names,
            "trained_at": datetime.now(timezone.utc).isoformat(),""",
        "new": """            "feature_names": feature_names,
            "feature_baseline": getattr(model, "_feature_baseline", None),
            "frozen_holdout": _setup_fh_stamp(),
            "trained_at": datetime.now(timezone.utc).isoformat(),""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "V7b: holdout stamp import in _save_setup_model_to_db",
        "marker": "frozen_holdout_stamp as _setup_fh_stamp",
        "old": """        from services.ai_modules.setup_training_config import get_model_name
        col = self._db["setup_type_models"]""",
        "new": """        from services.ai_modules.setup_training_config import get_model_name
        from services.ai_modules.frozen_holdout import frozen_holdout_stamp as _setup_fh_stamp
        col = self._db["setup_type_models"]""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "V8: PBO shadow log for setup models",
        "marker": "[PBO-GATE shadow] setup model",
        "old": """                num_classes=num_classes,
                event_intervals=_setup_iv,
            )""",
        "new": """                num_classes=num_classes,
                event_intervals=_setup_iv,
            )

            # v321 Tier-3b (shadow-only for setup models this round): log what
            # the PBO gate would decide. Enforcement comes after we see the
            # fleet-wide PBO distribution from the first CPCV retrain.
            try:
                from .timeseries_gbm import pbo_gate_check
                _pv, _pr = pbo_gate_check(
                    metrics.to_dict() if metrics else {},
                    f"setup_{setup_type}_{bar_size}",
                )
                if _pv != "pass":
                    logger.warning(
                        f"[PBO-GATE shadow] setup model {setup_type}/{bar_size}: "
                        f"WOULD BLOCK — {_pr}"
                    )
            except Exception:
                pass""",
    },
    {
        "file": "services/ai_modules/timeseries_service.py",
        "name": "V9: feature baseline for inline full-universe trainer",
        "marker": "model._feature_baseline = compute_feature_baseline(",
        "old": """            model._model = trained_model
            model._num_classes = 3
            model._feature_names = list(feature_names)""",
        "new": """            model._model = trained_model
            model._num_classes = 3
            model._feature_names = list(feature_names)
            # v321 Tier-3a-lite: training feature distribution baseline
            try:
                from services.ai_modules.feature_baseline import compute_feature_baseline
                model._feature_baseline = compute_feature_baseline(X, list(feature_names))
            except Exception:
                model._feature_baseline = None""",
    },
    # ──────────────────────── training_pipeline.py ───────────────────────
    {
        "file": "services/ai_modules/training_pipeline.py",
        "name": "V10a: NVMe bar-cache path embeds hold-out cutoff",
        "marker": "def _fh_cache_tag()",
        "old": """def _bar_cache_path(symbol: str, bar_size: str) -> str:
    bs_dir = f"{BAR_CACHE_DIR}/{_sanitize_bar_size(bar_size)}"
    _os.makedirs(bs_dir, exist_ok=True)
    return f"{bs_dir}/{symbol}.pkl\"""",
        "new": """def _fh_cache_tag() -> str:
    \"\"\"v321: frozen-holdout cache-key segment. Cached bars/features are stored
    POST-filter, so the cutoff must be part of the cache identity — changing
    TB_FROZEN_HOLDOUT_DAYS then auto-invalidates stale NVMe caches.\"\"\"
    try:
        from services.ai_modules.frozen_holdout import holdout_days
        return f"_fh{holdout_days()}"
    except Exception:
        return ""


def _bar_cache_path(symbol: str, bar_size: str) -> str:
    bs_dir = f"{BAR_CACHE_DIR}/{_sanitize_bar_size(bar_size)}"
    _os.makedirs(bs_dir, exist_ok=True)
    return f"{bs_dir}/{symbol}{_fh_cache_tag()}.pkl\"""",
    },
    {
        "file": "services/ai_modules/training_pipeline.py",
        "name": "V10b: NVMe feature-cache path embeds hold-out cutoff",
        "marker": "{symbol}{_fh_cache_tag()}.npy",
        "old": """def _feature_cache_path(symbol: str, bar_size: str) -> str:
    bs_dir = f"{FEATURE_CACHE_DIR}/{_sanitize_bar_size(bar_size)}"
    _os.makedirs(bs_dir, exist_ok=True)
    return f"{bs_dir}/{symbol}.npy\"""",
        "new": """def _feature_cache_path(symbol: str, bar_size: str) -> str:
    bs_dir = f"{FEATURE_CACHE_DIR}/{_sanitize_bar_size(bar_size)}"
    _os.makedirs(bs_dir, exist_ok=True)
    return f"{bs_dir}/{symbol}{_fh_cache_tag()}.npy\"""",
    },
    {
        "file": "services/ai_modules/training_pipeline.py",
        "name": "V11: frozen hold-out in load_symbol_bars (filter BEFORE caching)",
        "marker": "bars = apply_frozen_holdout(bars, symbol, bar_size)",
        "old": """        bars = await asyncio.wait_for(
            loop.run_in_executor(TRAINING_POOL, _run_query),
            timeout=90
        )
        # Write to NVMe disk cache for reuse by later phases
        if bars:
            _cache_bars_to_disk(symbol, bar_size, bars)
        return bars""",
        "new": """        bars = await asyncio.wait_for(
            loop.run_in_executor(TRAINING_POOL, _run_query),
            timeout=90
        )
        # v321 Tier-2b: frozen forward hold-out — filter BEFORE caching so the
        # NVMe cache (whose filename embeds the cutoff) stores filtered bars.
        try:
            from services.ai_modules.frozen_holdout import apply_frozen_holdout
            bars = apply_frozen_holdout(bars, symbol, bar_size)
        except Exception:
            pass
        # Write to NVMe disk cache for reuse by later phases
        if bars:
            _cache_bars_to_disk(symbol, bar_size, bars)
        return bars""",
    },
    # ──────────────────────── scripts/local_train.py ───────────────────────
    {
        "file": "scripts/local_train.py",
        "name": "V12a: local_train holdout import + banner",
        "marker": "FROZEN HOLD-OUT active",
        "old": """    symbols = [doc["_id"] for doc in db.ib_historical_data.aggregate(pipeline)]
    print(f"Found {len(symbols):,} symbols with {timeframe} data")""",
        "new": """    symbols = [doc["_id"] for doc in db.ib_historical_data.aggregate(pipeline)]
    print(f"Found {len(symbols):,} symbols with {timeframe} data")

    # v321 Tier-2b: frozen forward hold-out for the standalone trainer
    try:
        from services.ai_modules.frozen_holdout import apply_frozen_holdout as _afh, holdout_cutoff_iso as _hco
    except ImportError:
        import sys as _sys
        import os as _os2
        _sys.path.insert(0, _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__))))
        try:
            from services.ai_modules.frozen_holdout import apply_frozen_holdout as _afh, holdout_cutoff_iso as _hco
        except Exception:
            _afh, _hco = None, None
    if _afh is not None and _hco():
        print(f"FROZEN HOLD-OUT active: training excludes bars after {_hco()}")
    elif _afh is None:
        print("WARNING: frozen_holdout module not importable — hold-out NOT applied")""",
    },
    {
        "file": "scripts/local_train.py",
        "name": "V12b: local_train applies holdout per symbol",
        "marker": "data = _afh(data, symbol, timeframe)",
        "old": """                data = list(cursor)
                if len(data) < 25:
                    continue""",
        "new": """                data = list(cursor)
                if _afh is not None:
                    data = _afh(data, symbol, timeframe)
                if len(data) < 25:
                    continue""",
    },
]


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

    # Prerequisite: the new module files must exist before wiring them in.
    missing = [
        rel for rel in (
            "services/ai_modules/frozen_holdout.py",
            "services/ai_modules/feature_baseline.py",
        ) if not os.path.exists(os.path.join(backend, rel))
    ]
    if missing:
        print("✗ PREREQUISITE MISSING — download the new module files first:")
        for rel in missing:
            print(f"    {rel}")
        sys.exit(2)
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
