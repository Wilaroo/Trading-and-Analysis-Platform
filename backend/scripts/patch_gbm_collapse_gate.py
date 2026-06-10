#!/usr/bin/env python3
"""
patch_gbm_collapse_gate.py  —  v19.34.312  (2026-06-10)

Idempotent patcher: adds an ABSOLUTE class-collapse unfitness gate to
TimeSeriesGBM._save_model (services/ai_modules/timeseries_gbm.py).

A freshly trained 2-class model whose minimum per-class recall < floor
(default 0.10, env GBM_ABS_MIN_RECALL) is NOT promoted to the live inference
collection — even on first-train, where the existing RELATIVE guard is skipped.
This is the hole that let gap_fill (0.98 acc / recall_down 0.00 → always "FILL")
and vol_predictor (always "HIGH_VOL") ship as fake "edge".

Run on the DGX:
    cd ~/Trading-and-Analysis-Platform/backend && \
      .venv/bin/python scripts/patch_gbm_collapse_gate.py
    (then)  cd .. && ./start_backend.sh --force      # (no restart strictly needed;
                                                       #  takes effect next training run)
"""
import os
import sys

TARGET = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "services", "ai_modules", "timeseries_gbm.py"
))

ANCHOR = """            # Step 2: Check current active model's accuracy
            current_active = self._db[self.MODEL_COLLECTION].find_one(
                {"name": self.model_name},
                {"metrics": 1, "version": 1, "_id": 0}
            )
            
            should_promote = True
            demotion_reason = None"""

REPLACEMENT = """            # Step 2: Check current active model's accuracy
            current_active = self._db[self.MODEL_COLLECTION].find_one(
                {"name": self.model_name},
                {"metrics": 1, "version": 1, "_id": 0}
            )

            # v19.34.312: ABSOLUTE class-collapse unfitness gate.
            # The relative guard below only runs when an active model already
            # exists, so the FIRST training of a model (and every vol_predictor_*
            # / gap_fill_* family, which bypassed the direction-only path) could
            # ship a model that ignores one class entirely — e.g. gap_fill 0.98
            # accuracy with recall_down=0.00 (always "FILL"), vol_predictor
            # always-"HIGH_VOL". Headline accuracy is then just the base rate:
            # zero tradeable edge. Refuse to promote such a model to the LIVE
            # inference collection regardless of accuracy or whether an active
            # model exists. Archive it as rejected_class_collapse for audit.
            import os as _os_abs
            ABS_MIN_RECALL = float(_os_abs.environ.get("GBM_ABS_MIN_RECALL", "0.10"))
            _nm_abs = self._metrics.to_dict() if self._metrics else {}
            _abs_ru = float(_nm_abs.get("recall_up", 0.0))
            _abs_rd = float(_nm_abs.get("recall_down", 0.0))
            if min(_abs_ru, _abs_rd) < ABS_MIN_RECALL:
                logger.warning(
                    f"Model protection: NEW {self._version} of {self.model_name} "
                    f"REJECTED (class collapse) — recall_up={_abs_ru:.3f}, "
                    f"recall_down={_abs_rd:.3f} < floor {ABS_MIN_RECALL}. "
                    f"Headline accuracy {new_accuracy:.4f} is base-rate only; NOT "
                    f"promoted to live inference. Archived as rejected_class_collapse."
                )
                try:
                    self._db[self.MODEL_ARCHIVE_COLLECTION].update_one(
                        {"name": self.model_name, "version": self._version},
                        {"$set": {
                            "rejected_reason": "class_collapse",
                            "rejected_recall_up": _abs_ru,
                            "rejected_recall_down": _abs_rd,
                        }},
                    )
                except Exception:
                    pass
                # Keep any existing (presumably non-collapsed) active model.
                if current_active is not None:
                    self._load_model()
                return "rejected_class_collapse"

            should_promote = True
            demotion_reason = None"""

MARKER = "v19.34.312: ABSOLUTE class-collapse unfitness gate"


def main():
    with open(TARGET) as f:
        src = f.read()
    if MARKER in src:
        print(f"[skip] Already patched (v19.34.312): {TARGET}")
        return 0
    if ANCHOR not in src:
        print("[ERROR] Anchor not found — file differs from expected. No changes made.")
        return 1
    with open(TARGET, "w") as f:
        f.write(src.replace(ANCHOR, REPLACEMENT, 1))
    print(f"[ok] Patched (v19.34.312): {TARGET}")
    print("     Takes effect on the next training run (no restart strictly required).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
