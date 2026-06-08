#!/usr/bin/env python3
"""
v19.34.305 — one-shot backfill: recompute every setup's `strategy_stats` doc
through the artifact-free `pnl_compute.recompute_strategy_stats_for_setup`, so
the unified realized-mean EV (== avg_r) lands on every doc NOW instead of
waiting for each setup's next trade close. Safe to re-run anytime.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/recompute_all_strategy_stats.py
"""
import os

# load backend/.env into the environment (no heredoc; DGX-safe)
for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402
from services.pnl_compute import (  # noqa: E402
    recompute_strategy_stats_for_setup,
    _base_setup,
)


def main():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    bases = sorted({_base_setup(x) for x in db.alert_outcomes.distinct("setup_type") if x})
    bases = [b for b in bases if b]
    print(f"recomputing {len(bases)} setup families…")
    ok = 0
    for b in bases:
        doc = recompute_strategy_stats_for_setup(b, genuine_only=True)
        if doc is not None:
            ok += 1
            print(f"  {b:<28} EV={doc['expected_value_r']:+.3f}R "
                  f"avg_r={doc.get('avg_r'):+.3f}R win={doc['win_rate']*100:.0f}% "
                  f"n={doc['alerts_triggered']}")
    print(f"done — {ok}/{len(bases)} recomputed (EV now == avg_r on every doc)")


if __name__ == "__main__":
    main()
