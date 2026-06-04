#!/usr/bin/env python3
"""
apply_v19_34_266.py  —  Idempotent applier for v19.34.266
=========================================================
Adds an explicit per-setup MICRO list to opportunity_evaluator: any
setup_type named in the MICRO_SETUPS env var trades at 0.1x learning-only
size (excluded from grade aggregation), regardless of its rolling grade.

Motivation: the MAE/MFE bar-reconstruction flagged vwap_fade_short,
vwap_fade_long, mean_reversion_short and daily_breakout with negative
MANAGED edge (mgdR ≈ -1.0). Two of them grade as "passing" on outlier-
inflated avg_R, so the F-gate misses them. This knob micro-sizes them so
we keep gathering clean data without freezing their stats.

SAFE TO RUN MULTIPLE TIMES (guarded by the v19.34.266 marker).

After it reports OK, set the list in backend/.env and restart:
    MICRO_SETUPS=vwap_fade_short,vwap_fade_long,mean_reversion_short,daily_breakout
    ./start_backend.sh --force

Run from repo root:  .venv/bin/python /tmp/apply_v19_34_266.py
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = '''            except Exception as _fg_err:
                logger.debug(f"v19.34.173 F-gate check error: {_fg_err}")
'''

NEW = '''            except Exception as _fg_err:
                logger.debug(f"v19.34.173 F-gate check error: {_fg_err}")

            # ── v19.34.266 — explicit per-setup MICRO list ───────────────
            # Operator-driven 0.1x learning-only sizing for named setups
            # whose MANAGED (bar-reconstructed MAE/MFE) edge is negative
            # regardless of bracket — e.g. vwap_fade_*, mean_reversion_short,
            # daily_breakout (mgdR ≈ -1.0). Unlike the F-gate this does NOT
            # depend on the rolling grade (some of these grade as "passing"
            # on outlier-inflated avg_R, so the F-gate misses them). Keeps
            # them trading tiny so we keep gathering clean data instead of
            # freezing their stats. Comma-separated env list; fully reversible.
            try:
                import os as _os_ms
                _micro_raw = _os_ms.environ.get("MICRO_SETUPS", "") or ""
                _micro_set = {s.strip() for s in _micro_raw.split(",") if s.strip()}
                if setup_type and setup_type in _micro_set and not alert.get("learning_only"):
                    alert["learning_only"] = True
                    logger.info(
                        "🧪 [v19.34.266 MICRO-SETUP] %s %s in MICRO_SETUPS — trading as "
                        "learning_only at 0.1x (negative managed edge; gathering data).",
                        symbol, setup_type,
                    )
            except Exception as _ms_err:
                logger.debug(f"v19.34.266 micro-setup check error: {_ms_err}")
'''


def _repo_root() -> Path:
    for c in (Path.cwd(), Path.home() / "Trading-and-Analysis-Platform"):
        if (c / "backend" / "services" / "opportunity_evaluator.py").exists():
            return c
    print("ERROR: could not locate repo root."); sys.exit(1)


def main() -> None:
    root = _repo_root()
    path = root / "backend" / "services" / "opportunity_evaluator.py"
    text = path.read_text()
    if "v19.34.266 — explicit per-setup MICRO list" in text:
        print("⏭  already applied (no-op).")
        return
    if OLD not in text:
        print("✗ anchor NOT found — file drifted, NO change made."); sys.exit(1)
    if text.count(OLD) != 1:
        print(f"✗ anchor matched {text.count(OLD)}× (expected 1) — skipped."); sys.exit(1)
    path.write_text(text.replace(OLD, NEW))
    print("✓ v19.34.266 applied to opportunity_evaluator.py")
    print("\nNext: add to backend/.env and restart:")
    print("  MICRO_SETUPS=vwap_fade_short,vwap_fade_long,mean_reversion_short,daily_breakout")
    print("  ./start_backend.sh --force")


if __name__ == "__main__":
    main()
