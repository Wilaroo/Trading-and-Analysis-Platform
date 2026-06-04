#!/usr/bin/env python3
"""
verify_v263.py  (read-only) — confirm the v19.34.263 LEARNING-LOOP change.

The diag_scalp_exit_truth probe re-derives exits straight from bot_trades, so it
looks the same before/after. THIS checks what v263 actually changed:
  1) alert_outcomes: external-reason rows now carry effective_close_reason +
     reclass_method, and the genuine flag reflects the price-confirmed fills.
  2) strategy_stats: scalp/intraday-family EV + sample size (post-recompute).

Read-only. MONGO_URL + DB_NAME from backend/.env. Run from repo root:
    curl -s <this-url> | python3 -
"""
from __future__ import annotations
import os
from collections import Counter
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def main():
    _load_env()
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        return
    db = MongoClient(url)[name]
    print(f"[db] {name} @ {url.split('@')[-1]}")

    ao = db["alert_outcomes"]
    ext = list(ao.find(
        {"close_reason": {"$regex": "oca_closed_externally|external_close", "$options": "i"}},
        {"_id": 0, "genuine": 1, "effective_close_reason": 1, "reclass_method": 1,
         "close_reason": 1, "setup_type": 1}))

    print("\n" + "=" * 64)
    print(f"alert_outcomes — external bracket rows: {len(ext)}")
    print("=" * 64)
    g = Counter(str(d.get("genuine")) for d in ext)
    print(f"  genuine:   True={g.get('True', 0)}  False={g.get('False', 0)}  None={g.get('None', 0)}")
    eff = Counter(d.get("effective_close_reason") for d in ext if d.get("effective_close_reason"))
    print(f"  effective_close_reason present on {sum(eff.values())} rows:")
    for k, c in eff.most_common():
        print(f"      {k:<22} {c}")
    meth = Counter(d.get("reclass_method") for d in ext if d.get("reclass_method"))
    if meth:
        print(f"  reclass_method: " + "  ".join(f"{k}={c}" for k, c in meth.most_common()))

    print("\n" + "=" * 64)
    print("strategy_stats — scalp/intraday-family EV (genuine sample)")
    print("=" * 64)
    fams = ("scalp", "nine_ema_scalp", "spencer_scalp", "abc_scalp",
            "vwap_reclaim", "orb", "opening_drive", "momentum_ignition",
            "gap_give_go", "gap_fade", "hod_breakout", "mean_reversion")
    ss = db["strategy_stats"]
    any_hit = False
    for f in fams:
        doc = ss.find_one({"setup_type": f}, {"_id": 0})
        if not doc:
            continue
        any_hit = True
        print(f"  {f:<20} n={doc.get('alerts_triggered', 0):>4}  "
              f"win={doc.get('win_rate', 0) * 100:5.1f}%  "
              f"EV={doc.get('expected_value_r', 0):+.3f}R  "
              f"PF={doc.get('profit_factor', 0):.2f}  "
              f"(updated {str(doc.get('last_updated', ''))[:19]})")
    if not any_hit:
        print("  (no scalp/intraday setup families found in strategy_stats —"
              " they may use different setup_type keys; check /api/setup-grades)")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
