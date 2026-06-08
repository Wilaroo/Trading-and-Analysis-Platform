#!/usr/bin/env python3
"""
v19.34.306 — backfill historical `alert_outcomes.r_multiple` to the POSITION-
WEIGHTED blended trade R, fixing the scale-out runner-leg inflation that the
single-leg calc baked into closed trades (e.g. daily_breakout +2.32R / ~8R).

Canonical R for a closed trade:
    blended_r = realized_pnl_total / (|fill_price - stop_price| * original_shares)
where realized_pnl_total is the IB-reconciled cumulative P&L across ALL legs
(persisted on bot_trades.realized_pnl, "Cumulative from all scale-outs + final
exit"). This is correct for single-exit trades too (it reduces to the same
number), so we recompute every eligible row.

DRY-RUN by default — shows how many rows would change and the per-setup EV delta.
Re-run with --apply to write, then run recompute_all_strategy_stats.py.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/backfill_blended_r_v306.py          # dry-run
  PYTHONPATH=backend .venv/bin/python backend/scripts/backfill_blended_r_v306.py --apply   # write
"""
import os
import sys
from collections import defaultdict

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

APPLY = "--apply" in sys.argv


def _blended_r(bt):
    """Returns (r_multiple_or_None, risk_unreliable_bool).
    r is None when the risk basis is corrupt (stop ≈ entry / |R|>20) so callers
    null + flag the row instead of storing garbage."""
    try:
        entry = float(bt.get("fill_price") or 0)
        stop = float(bt.get("stop_price") or bt.get("stop_loss") or 0)
        orig = int(abs(bt.get("original_shares") or bt.get("shares") or 0))
        realized = bt.get("realized_pnl")
        if entry <= 0 or stop <= 0 or orig <= 0 or realized is None:
            return None, False
        rps = abs(entry - stop)
        # v19.34.307 — reject corrupt risk basis (stop ~ entry → tiny denominator
        # → absurd R like -28R). A real protective stop is a plausible distance.
        if rps < max(0.01, 0.0015 * entry):
            return None, True
        r = round(float(realized) / (rps * orig), 3)
        if abs(r) > 20.0:
            return None, True  # corrupt — don't trust this R
        return r, False
    except Exception:
        return None, False


def main():
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    ao = db.alert_outcomes
    bt_coll = db.bot_trades

    # Index closed bot_trades by trade id for the join.
    bt_by_id = {}
    for bt in bt_coll.find(
        {"status": {"$in": ["closed", "CLOSED"]}},
        {"id": 1, "trade_id": 1, "fill_price": 1, "stop_price": 1, "stop_loss": 1,
         "original_shares": 1, "shares": 1, "realized_pnl": 1, "setup_type": 1},
    ):
        key = bt.get("id") or bt.get("trade_id")
        if key:
            bt_by_id[str(key)] = bt

    changed = 0
    inspected = 0
    delta_by_setup = defaultdict(lambda: {"old": [], "new": [], "n": 0})
    ops = []

    for row in ao.find({}, {"trade_id": 1, "alert_id": 1, "setup_type": 1, "r_multiple": 1}):
        tid = str(row.get("trade_id") or row.get("alert_id") or "")
        bt = bt_by_id.get(tid)
        if not bt:
            continue
        inspected += 1
        new_r, unreliable = _blended_r(bt)
        old_r = row.get("r_multiple")
        setup = row.get("setup_type") or bt.get("setup_type") or "?"
        if unreliable:
            # corrupt risk basis → null the R + flag so EV recompute excludes it
            changed += 1
            if APPLY:
                from pymongo import UpdateOne
                ops.append(UpdateOne(
                    {"_id": row["_id"]},
                    {"$set": {"r_multiple": None, "r_risk_unreliable": True}}))
            continue
        if new_r is None:
            continue
        if old_r is not None:
            delta_by_setup[setup]["old"].append(float(old_r))
        delta_by_setup[setup]["new"].append(new_r)
        delta_by_setup[setup]["n"] += 1
        if old_r is None or abs(float(old_r) - new_r) > 0.001:
            changed += 1
            if APPLY:
                from pymongo import UpdateOne
                ops.append(UpdateOne({"_id": row["_id"]},
                                     {"$set": {"r_multiple": new_r,
                                               "r_risk_unreliable": False,
                                               "r_multiple_blended_v306": True}}))

    print(f"inspected {inspected} alert_outcomes rows joined to closed bot_trades")
    print(f"{changed} rows differ from the new blended R\n")
    print(f"{'setup':<26}{'n':>4}  {'old avg_r':>10}  {'new avg_r':>10}  {'Δ':>8}")
    print("-" * 70)
    for setup in sorted(delta_by_setup, key=lambda s: -delta_by_setup[s]["n"]):
        d = delta_by_setup[setup]
        oa = sum(d["old"]) / len(d["old"]) if d["old"] else 0.0
        na = sum(d["new"]) / len(d["new"]) if d["new"] else 0.0
        flag = "  <== inflated" if (oa - na) > 0.25 else ""
        print(f"{setup:<26}{d['n']:>4}  {oa:>+9.3f}R  {na:>+9.3f}R  {na-oa:>+7.3f}{flag}")

    if APPLY and ops:
        res = ao.bulk_write(ops, ordered=False)
        print(f"\nAPPLIED: modified {res.modified_count} rows.")
        print("Now run: PYTHONPATH=backend .venv/bin/python "
              "backend/scripts/recompute_all_strategy_stats.py")
    elif APPLY:
        print("\nAPPLY requested but no rows needed changing.")
    else:
        print("\nDRY-RUN only. Re-run with --apply to write, then recompute strategy_stats.")


if __name__ == "__main__":
    main()
