#!/usr/bin/env python3
"""
refresh_regime_expectancy.py  (T6, fork 2026-06)
================================================
Recompute the per-(setup × direction × regime_band) expectancy table from
bot_trades and (optionally) preview what the gate WOULD suppress / flip the mode.

USAGE (from repo root, on the DGX):
  # Refresh the table + print the full would-suppress preview (default):
  PYTHONPATH=backend .venv/bin/python backend/scripts/refresh_regime_expectancy.py

  # Just preview, do NOT rewrite the table:
  PYTHONPATH=backend .venv/bin/python backend/scripts/refresh_regime_expectancy.py --preview-only

  # Flip enforcement on/off (default is 'shadow'):
  PYTHONPATH=backend .venv/bin/python backend/scripts/refresh_regime_expectancy.py --set-mode active
  PYTHONPATH=backend .venv/bin/python backend/scripts/refresh_regime_expectancy.py --set-mode shadow

Refreshing is READ-ONLY on bot_trades; it only writes the
`setup_regime_expectancy` collection.
"""
import argparse
import os
import sys

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, "backend")

from pymongo import MongoClient  # noqa: E402
from services.ai_modules.regime_expectancy_calibrator import (  # noqa: E402
    RegimeExpectancyCalibrator, decide_suppression, HARD_R, SOFT_R, MIN_EFF_N,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview-only", action="store_true")
    ap.add_argument("--set-mode", choices=["shadow", "active"])
    args = ap.parse_args()

    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    cal = RegimeExpectancyCalibrator(db=db)

    if args.set_mode:
        m = cal.set_mode(args.set_mode)
        print(f"Regime suppression mode set to: {m}")
        return

    if not args.preview_only:
        res = cal.refresh()
        print(f"Refresh: {res}")

    doc = cal.load()
    mode = cal.load_mode()
    if not doc or not doc.get("cells"):
        print("No expectancy table available (no qualifying closed trades?).")
        return

    cells = doc["cells"]
    params = doc.get("params", {})
    print("=" * 96)
    print(f"REGIME EXPECTANCY  |  mode={mode}  |  cells={doc.get('cell_count')}  "
          f"|  HARD<= {HARD_R}  SOFT<= {SOFT_R}  MIN_EFF_N>= {MIN_EFF_N}")
    print(f"generated_at={doc.get('generated_at')}")
    print("=" * 96)

    # Only the direction-scoped cells (the ones the gate prefers); sorted worst-first.
    rows = []
    for key, c in cells.items():
        parts = key.split("|")
        if len(parts) != 3:
            continue  # skip the (setup|band) fallback rows in this view
        setup, direction, band = parts
        sup = decide_suppression(cells, setup, direction, band, params)
        rows.append((c.get("weighted_mean_r") if c.get("weighted_mean_r") is not None else 0.0,
                     key, c, sup))
    rows.sort(key=lambda r: r[0])

    hdr = f"{'cell':<46}{'wR':>8}{'effN':>7}{'rawN':>6}  {'30d':>7}{'90d':>7}{'all':>7}  action"
    print(hdr)
    print("-" * len(hdr))
    for wr, key, c, sup in rows:
        d = c.get("diag", {})
        def f(x):
            return f"{x:+.2f}" if isinstance(x, (int, float)) else "   -"
        flag = "" if sup["action"] == "NONE" else f"  <== {sup['action']}"
        print(f"{key:<46}{f(c.get('weighted_mean_r')):>8}{c.get('eff_n', 0):>7.1f}"
              f"{c.get('raw_n', 0):>6}  {f(d.get('r_30d')):>7}{f(d.get('r_90d')):>7}"
              f"{f(d.get('r_all')):>7}{flag}")

    n_skip = sum(1 for *_, s in rows if s["action"] == "SKIP")
    n_red = sum(1 for *_, s in rows if s["action"] == "REDUCE")
    print("-" * len(hdr))
    print(f"WOULD SUPPRESS: {n_skip} SKIP, {n_red} REDUCE  "
          f"({'ENFORCED' if mode == 'active' else 'shadow — not enforced'})")


if __name__ == "__main__":
    main()
