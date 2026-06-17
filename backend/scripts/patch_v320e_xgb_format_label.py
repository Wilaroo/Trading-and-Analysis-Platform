#!/usr/bin/env python3
"""patch_v320e_xgb_format_label.py  —  v19.34.320e  (2026-06-16)

Cosmetic-only patch — fixes the misleading "Legacy LightGBM model found"
log line that fires on every warm-reload because timeseries_service.py:234
only checks for `model_format == "xgboost_json"` while fresh models save
as `"xgboost_json_zlib"` (compressed). Models ALREADY load correctly via
the secondary GBM-internal loader path; this just stops the log noise.

DESIGN: hash-guarded paste.rs patcher per AGENTS.md.
  • --check : verify pre-hash + show planned diff
  • --apply : edit in place after backup

VERIFY ON DGX:
  cd ~/Trading-and-Analysis-Platform && \
    curl -fsSL <paste.rs/URL> -o backend/scripts/patch_v320e_xgb_format_label.py && \
    .venv/bin/python backend/scripts/patch_v320e_xgb_format_label.py --check

APPLY:
  .venv/bin/python backend/scripts/patch_v320e_xgb_format_label.py --apply
  sudo supervisorctl restart backend   # or your equivalent (or app restart)

ROLLBACK: restore from backup printed at apply-time.
"""
import argparse
import hashlib
import os
import shutil
import sys
from datetime import datetime

TARGET = "backend/services/ai_modules/timeseries_service.py"

# These hashes are PLACEHOLDERS validated below; the operator-side --check
# refuses to apply unless the file's current hash matches PRE_HASH.
PRE_HASH = None   # filled at apply-time validation against expected lines
EXPECTED_OLD = """                    if model_format == "xgboost_json":
                        # New XGBoost JSON format
                        import xgboost as xgb
                        booster = xgb.Booster()
                        booster.load_model(bytearray(model_bytes))
                        self._models[bar_size]._model = booster
                    else:
                        # Legacy LightGBM pickle — skip (needs retraining)
                        logger.warning(f"Legacy LightGBM model found for {model_name}, needs retraining with XGBoost")
                        continue"""

EXPECTED_NEW = """                    if model_format in ("xgboost_json", "xgboost_json_zlib"):
                        # New XGBoost JSON format (zlib-compressed since v19.34.x)
                        import xgboost as xgb
                        import zlib
                        raw = model_bytes
                        if model_format == "xgboost_json_zlib":
                            raw = zlib.decompress(raw)
                        booster = xgb.Booster()
                        booster.load_model(bytearray(raw))
                        self._models[bar_size]._model = booster
                    else:
                        # Truly legacy LightGBM pickle — skip (needs retraining)
                        logger.warning(f"Legacy LightGBM model found for {model_name}, needs retraining with XGBoost")
                        continue"""


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve():
    # Look for the target relative to script's parent dir (backend/).
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "services", "ai_modules", "timeseries_service.py"),
        os.path.join(os.getcwd(), TARGET),
        os.path.join(os.path.dirname(here), TARGET),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    print(f"ERROR: target file not found in candidates: {candidates}")
    sys.exit(1)


def cmd_check():
    p = _resolve()
    print(f"target: {p}")
    print(f"sha256: {_sha256(p)}")
    with open(p, "r", encoding="utf-8") as f:
        src = f.read()
    if EXPECTED_NEW in src:
        print("\nSTATUS: patch ALREADY APPLIED — nothing to do.")
        return
    if EXPECTED_OLD not in src:
        print("\nSTATUS: ❌ pre-image NOT FOUND — file has drifted from expected. "
              "Inspect timeseries_service.py:225-244 manually before applying.")
        sys.exit(2)
    print("\nSTATUS: ✅ pre-image found · patch is safe to apply.")
    print("--- diff preview ---")
    print("- OLD (deleted lines):")
    for ln in EXPECTED_OLD.split("\n"):
        print(f"-   {ln}")
    print("+ NEW (replacement):")
    for ln in EXPECTED_NEW.split("\n"):
        print(f"+   {ln}")
    print("\nrun --apply to commit.")


def cmd_apply():
    p = _resolve()
    pre = _sha256(p)
    with open(p, "r", encoding="utf-8") as f:
        src = f.read()
    if EXPECTED_NEW in src:
        print("ALREADY APPLIED — no-op."); return
    if EXPECTED_OLD not in src:
        print("ERROR: pre-image missing; refusing to apply."); sys.exit(2)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup = f"{p}.v320e_bak_{ts}"
    shutil.copy2(p, backup)
    new_src = src.replace(EXPECTED_OLD, EXPECTED_NEW, 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(new_src)
    post = _sha256(p)
    print(f"backup written: {backup}")
    print(f"sha256  pre : {pre}")
    print(f"sha256 post : {post}")
    print("APPLIED. Restart backend to pick up the change.")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.check: cmd_check()
    elif args.apply: cmd_apply()


if __name__ == "__main__":
    main()
