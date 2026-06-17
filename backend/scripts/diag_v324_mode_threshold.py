#!/usr/bin/env python3
"""
v324 — TRADING-MODE / GO-THRESHOLD / REGIME-DOWNGRADE DIAGNOSTIC (READ-ONLY)

v323 showed GO never occurs below score 50 while 100 decisions scoring 35-48 are
held at REDUCE — i.e. the effective GO bar is ~50, not the NORMAL 38. This diag
disambiguates WHY:
  (a) trading_mode is elevated (CAUTIOUS=50 / DEFENSIVE=60), or
  (b) regime layer DOWNGRADES GO-eligible scores to REDUCE, or
  (c) regime_suppression SKIPs them.
…and quantifies the unlock: how many more GO if the bar were the NORMAL 38.

Reads confidence_gate_log only.

Usage:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v324_mode_threshold.py --hours 8
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

GO_THRESH = {"normal": 38, "cautious": 50, "defensive": 60, "aggressive": 28}
NORMAL = 38


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    hours = 8
    if "--hours" in sys.argv:
        try:
            hours = int(sys.argv[sys.argv.index("--hours") + 1])
        except Exception:
            hours = 8
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = list(db.confidence_gate_log.find(
        {"timestamp": {"$gte": iso}},
        {"_id": 0, "decision": 1, "confidence_score": 1, "trading_mode": 1,
         "regime_state": 1, "regime_score": 1, "regime_suppression": 1}))

    print(f"\n=== v324 MODE / THRESHOLD / REGIME-DOWNGRADE — last {hours}h ===\n")
    if not rows:
        print("  No decisions in window.\n"); return
    print(f"  decisions: {len(rows)}")

    # ---- trading_mode × decision ----
    print("\n" + "=" * 72)
    print("TRADING_MODE × decision  (effective GO bar per mode)")
    print("=" * 72)
    by_mode = defaultdict(lambda: {"GO": [], "REDUCE": [], "SKIP": []})
    for r in rows:
        m = str(r.get("trading_mode") or "?").lower()
        d = r.get("decision", "?")
        cs = _f(r.get("confidence_score"))
        if d in by_mode[m] and cs is not None:
            by_mode[m][d].append(cs)
    print(f"  {'mode':<11} {'GOthr':>5} {'GO':>5} {'RED':>5} {'SKIP':>6} {'GOmin':>6} {'REDmax':>7}")
    for m, dd in sorted(by_mode.items(), key=lambda x: -(len(x[1]['GO'])+len(x[1]['REDUCE'])+len(x[1]['SKIP']))):
        go, red, sk = dd["GO"], dd["REDUCE"], dd["SKIP"]
        gomin = f"{min(go):.0f}" if go else "-"
        redmax = f"{max(red):.0f}" if red else "-"
        print(f"  {m:<11} {GO_THRESH.get(m,'?'):>5} {len(go):>5} {len(red):>5} {len(sk):>6} "
              f"{gomin:>6} {redmax:>7}")

    # ---- GO-eligible-at-NORMAL (score>=38) that are NOT GO ----
    print("\n" + "=" * 72)
    print(f"GO-ELIGIBLE at NORMAL bar (score>={NORMAL}) but NOT GO — why?")
    print("=" * 72)
    eligible = [r for r in rows if (_f(r.get("confidence_score")) or 0) >= NORMAL]
    not_go = [r for r in eligible if r.get("decision") != "GO"]
    print(f"  score>={NORMAL}            : {len(eligible)}")
    print(f"  …of those NOT GO     : {len(not_go)}  (these would likely GO at NORMAL bar)")
    # attribute the block
    cause = Counter()
    for r in not_go:
        m = str(r.get("trading_mode") or "?").lower()
        if r.get("regime_suppression"):
            cause["regime_suppression"] += 1
        elif GO_THRESH.get(m, 38) > NORMAL:
            cause[f"mode_elevated({m}={GO_THRESH.get(m)})"] += 1
        else:
            cause["regime_downgrade_or_other"] += 1
    for k, c in cause.most_common():
        print(f"     {k:<32} {c}")

    # ---- current GO vs potential GO at NORMAL ----
    cur_go = sum(1 for r in rows if r.get("decision") == "GO")
    pot_go = len(eligible)  # everything scoring >=38 (minus genuine suppression)
    supp = sum(1 for r in eligible if r.get("regime_suppression"))
    print("\n" + "=" * 72)
    print("UNLOCK ESTIMATE")
    print("=" * 72)
    print(f"  current GO                         : {cur_go}")
    print(f"  score>={NORMAL} (GO-eligible at NORMAL) : {pot_go}")
    print(f"  …minus regime_suppression={supp}     : ~{pot_go - supp} potential GO at NORMAL bar")
    print(f"  → lowering the effective bar to {NORMAL} could ~{((pot_go - supp) / cur_go):.0f}x GO"
          if cur_go else "")

    # ---- regime context ----
    print("\n" + "=" * 72)
    print("REGIME context (is CAUTIOUS justified?)")
    print("=" * 72)
    rs_mode = Counter(str(r.get("trading_mode") or "?") for r in rows)
    print("  trading_mode mix : " + ", ".join(f"{k}={v}" for k, v in rs_mode.most_common()))
    regsc = [_f(r.get("regime_score")) for r in rows if _f(r.get("regime_score")) is not None]
    if regsc:
        regsc.sort()
        print(f"  regime_score     : min={regsc[0]:.0f} median={regsc[len(regsc)//2]:.0f} max={regsc[-1]:.0f}")
    st = Counter(str(r.get("regime_state") or "?") for r in rows)
    print("  regime_state mix : " + ", ".join(f"{k}={v}" for k, v in st.most_common(6)))

    print("\n=== READING THE RESULT ===")
    print("• If most 'NOT GO' are mode_elevated(cautious/defensive) → the bot is in a")
    print("    conservative mode raising the bar to 50/60. If regime_score is healthy and")
    print("    that caution is NOT warranted, recalibrating the mode→threshold map (or the")
    print("    regime→mode trigger) is the next lever — it could multiply GO several-fold.")
    print("• If most are regime_suppression → the EV-suppression layer is (correctly) killing")
    print("    negative-EV cells; leave it.")
    print("• If regime_downgrade_or_other dominates → GO→REDUCE downgrade logic is the lever.\n")


if __name__ == "__main__":
    main()
