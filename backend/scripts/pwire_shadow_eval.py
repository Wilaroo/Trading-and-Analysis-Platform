#!/usr/bin/env python3
"""
P-WIRE Shadow-Mode evaluation (run on the DGX once ~5000 decisions accrue).

Reads confidence_gate_log docs that carry live_prediction.regime_shadow and
measures whether the regime-specialized model would have beaten the generic
base model. Ground truth = the trade's realized outcome attributed by
decision_id (trade_outcome / outcome_pnl), per the confidence_gate_log schema.

Two complementary lenses:
  A) COVERAGE/AGREEMENT  — how often a regime variant exists & agrees with generic.
  B) EDGE (resolved only) — directional hit-rate & avg signed EV of each leg vs
     the actual realized trade direction (win => price moved with the entry).

Usage (from /app/backend):
    python3 scripts/pwire_shadow_eval.py
    python3 scripts/pwire_shadow_eval.py --min 200
"""
import argparse
import os
import sys
from collections import defaultdict

# Ensure backend/ is importable when run directly as scripts/pwire_shadow_eval.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient


def _outcome_dir(doc):
    """Map a resolved trade outcome to the direction price actually went,
    relative to the trade's intended direction. Returns 'up'/'down'/None."""
    out = doc.get("trade_outcome")
    pnl = doc.get("outcome_pnl")
    intended = (doc.get("direction") or "").lower()
    long_side = intended in ("long", "buy", "up")
    win = None
    if isinstance(out, str):
        if out.lower() in ("win", "won", "tp", "target"):
            win = True
        elif out.lower() in ("loss", "lost", "sl", "stop"):
            win = False
    if win is None and isinstance(pnl, (int, float)):
        win = pnl > 0
    if win is None:
        return None
    # If a long trade won, price went up; if a long lost, price went down.
    if long_side:
        return "up" if win else "down"
    return "down" if win else "up"


def _hit(leg_dir, actual_dir):
    if not leg_dir or leg_dir == "flat" or actual_dir is None:
        return None
    return leg_dir == actual_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=1, help="min shadow records to report")
    args = ap.parse_args()

    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    col = db["confidence_gate_log"]

    cur = col.find(
        {"live_prediction.regime_shadow": {"$exists": True}},
        {"live_prediction.regime_shadow": 1, "decision": 1, "direction": 1,
         "trade_outcome": 1, "outcome_pnl": 1, "outcome_tracked": 1, "regime_state": 1},
    )

    total = 0
    regime_dist = defaultdict(int)
    variant_available = 0
    agree = 0
    resolved = 0
    hits = {"generic": [0, 0], "regime": [0, 0]}      # [hits, scored]
    ev_sum = {"generic": 0.0, "regime": 0.0}
    ev_n = {"generic": 0, "regime": 0}

    for d in cur:
        sh = (d.get("live_prediction") or {}).get("regime_shadow")
        if not sh:
            continue
        total += 1
        regime_dist[sh.get("regime", "?")] += 1
        g = sh.get("generic_base", {})
        r = sh.get("regime_specialized", {})
        if r.get("available"):
            variant_available += 1
        if sh.get("directions_agree"):
            agree += 1

        actual = _outcome_dir(d) if d.get("outcome_tracked") else None
        if actual is not None:
            resolved += 1
            gh = _hit(g.get("direction"), actual)
            if gh is not None:
                hits["generic"][1] += 1
                hits["generic"][0] += int(gh)
            rh = _hit(r.get("direction"), actual) if r.get("available") else None
            if rh is not None:
                hits["regime"][1] += 1
                hits["regime"][0] += int(rh)
            # signed EV: ev_proxy aligned to realized direction
            if isinstance(g.get("ev_proxy"), (int, float)):
                ev_sum["generic"] += g["ev_proxy"] * (1 if actual == "up" else -1)
                ev_n["generic"] += 1
            if r.get("available") and isinstance(r.get("ev_proxy"), (int, float)):
                ev_sum["regime"] += r["ev_proxy"] * (1 if actual == "up" else -1)
                ev_n["regime"] += 1

    print("=" * 64)
    print("P-WIRE SHADOW EVALUATION")
    print("=" * 64)
    print(f"shadow records:        {total}")
    if total < args.min:
        print(f"(need >= {args.min} to report — accumulating)")
        return
    print(f"regime variant present: {variant_available}/{total} "
          f"({100*variant_available/max(total,1):.1f}%)")
    print(f"generic↔regime agree:   {agree}/{total} ({100*agree/max(total,1):.1f}%)")
    print(f"regime distribution:    {dict(regime_dist)}")
    print(f"resolved (w/ outcome):  {resolved}")
    print("-" * 64)

    def _rate(h):
        return f"{h[0]}/{h[1]} ({100*h[0]/h[1]:.1f}%)" if h[1] else "n/a"

    print(f"directional hit-rate  generic : {_rate(hits['generic'])}")
    print(f"directional hit-rate  regime  : {_rate(hits['regime'])}")
    gev = ev_sum['generic'] / ev_n['generic'] if ev_n['generic'] else 0.0
    rev = ev_sum['regime'] / ev_n['regime'] if ev_n['regime'] else 0.0
    print(f"avg signed EV         generic : {gev:+.4f} (n={ev_n['generic']})")
    print(f"avg signed EV         regime  : {rev:+.4f} (n={ev_n['regime']})")
    print("-" * 64)
    if hits["regime"][1] and hits["generic"][1]:
        gr = hits["generic"][0] / hits["generic"][1]
        rr = hits["regime"][0] / hits["regime"][1]
        verdict = ("REGIME WINS — wire it live" if rr > gr + 0.02
                   else "GENERIC HOLDS — keep regime models dead"
                   if gr > rr + 0.02 else "INCONCLUSIVE — keep accumulating")
        print(f"VERDICT: {verdict}  (regime {rr:.3f} vs generic {gr:.3f})")
    else:
        print("VERDICT: insufficient resolved overlap — keep accumulating")


if __name__ == "__main__":
    main()
