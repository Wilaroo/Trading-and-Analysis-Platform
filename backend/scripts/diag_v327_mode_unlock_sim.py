#!/usr/bin/env python3
"""
v327 — MODE-FIX UNLOCK SIMULATOR + REGIME-SUPPRESSION MODE (READ-ONLY)

CONTEXT (from v326): the classifier is NOT stuck — it varies day to day. The
100%-CAUTIOUS posture only appeared 2026-06-16/17, caused by SPY context flipping
to MIXED when the daily anchor was strongly UP (long lane 91) but the intraday
lane drifted to NEUTRAL (43-46). MIXED maps BOTH directions to 'cautious'
(multi_tf_regime.py L200-201), raising the GO bar 38→50 (confidence_gate L1026-1031).

Proposed lever: make the MIXED→mode map anchor-aware so a decisively-UP anchor
with a merely-NEUTRAL (not opposing) intraday keeps LONGS at NORMAL (go bar 38)
and SHORTS cautious — instead of flattening both to cautious.

BUT the GO unlock also depends on a SEPARATE gate: `regime_suppression`
(per setup×direction×regime-band expectancy, confidence_gate L1041-1080). It runs
in 'shadow' (logs only) or 'active' (hard SKIP / REDUCE). If ACTIVE-SKIP is
independently blocking the GO-eligible setups, the mode fix alone won't unlock them.

This diag reads confidence_gate_log over the window and answers, decisively:
  1. regime_suppression MODE (shadow vs active) + action distribution.
  2. UNLOCK SIM: of decisions currently NOT GO, how many would GO at the NORMAL
     bar (score>=38) IF NOT independently hard-blocked by an ACTIVE suppression SKIP.

Usage (DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v327_mode_unlock_sim.py --hours 8
"""
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

NORMAL_GO = 38      # confidence_gate L1027
NORMAL_REDUCE = 25  # confidence_gate L1028


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
         "regime_suppression": 1, "regime_score": 1, "setup_type": 1,
         "direction": 1, "timestamp": 1}))

    print(f"\n=== v327 MODE-FIX UNLOCK SIM — last {hours}h ===\n")
    if not rows:
        print("  No decisions in window.\n")
        return

    n = len(rows)
    dec = Counter(str(r.get("decision") or "?") for r in rows)
    modes = Counter(str(r.get("trading_mode") or "?") for r in rows)
    print(f"  decisions               : {n}")
    print(f"  decision mix            : " + ", ".join(f"{k}={v}" for k, v in dec.most_common()))
    print(f"  trading_mode mix        : " + ", ".join(f"{k}={v}" for k, v in modes.most_common()))

    # --- regime_suppression mode/action census ---
    print("\n" + "=" * 72)
    print("REGIME-SUPPRESSION GATE (independent of trading_mode)")
    print("=" * 72)
    supp_mode = Counter()
    supp_action = Counter()      # action among rows that HAVE a suppression dict
    active_skip = active_reduce = 0
    for r in rows:
        rs = r.get("regime_suppression")
        if not isinstance(rs, dict):
            supp_mode["<none>"] += 1
            continue
        m = str(rs.get("mode") or "?")
        a = str(rs.get("action") or "NONE")
        supp_mode[m] += 1
        supp_action[a] += 1
        if m == "active" and a == "SKIP":
            active_skip += 1
        elif m == "active" and a == "REDUCE":
            active_reduce += 1
    print(f"  suppression mode mix    : " + ", ".join(f"{k}={v}" for k, v in supp_mode.most_common()))
    print(f"  action mix (where set)  : " + ", ".join(f"{k}={v}" for k, v in supp_action.most_common()))
    print(f"  ACTIVE-SKIP rows        : {active_skip}   (these hard-block regardless of mode/score)")
    print(f"  ACTIVE-REDUCE rows      : {active_reduce}")
    if supp_mode.get("active", 0) == 0:
        print("  → suppression is SHADOW (log-only) ⇒ it is NOT the GO blocker; the")
        print("    cautious GO-bar (50) is. The anchor-aware MIXED mode fix should unlock GO.")
    else:
        print("  → suppression has ACTIVE rows ⇒ a mode fix will NOT unlock the ACTIVE-SKIP")
        print("    cells; those are intentional negative-EV benches. Quantified below.")

    # --- unlock simulation ---
    print("\n" + "=" * 72)
    print("UNLOCK SIM — if mode were NORMAL (GO bar 38), holding suppression as-is")
    print("=" * 72)
    not_go = [r for r in rows if r.get("decision") != "GO"]
    would_go = would_reduce = blocked_active = score_low = 0
    cautious_targeted = 0
    for r in not_go:
        cs = _f(r.get("confidence_score"))
        if cs is None:
            continue
        rs = r.get("regime_suppression") if isinstance(r.get("regime_suppression"), dict) else {}
        a_skip = rs.get("mode") == "active" and rs.get("action") == "SKIP"
        a_reduce = rs.get("mode") == "active" and rs.get("action") == "REDUCE"
        if cs < NORMAL_GO:
            if cs >= NORMAL_REDUCE:
                would_reduce += 1
            else:
                score_low += 1
            continue
        # cs >= 38: clears NORMAL GO bar
        if a_skip:
            blocked_active += 1
        elif a_reduce:
            would_reduce += 1
        else:
            would_go += 1
            if str(r.get("trading_mode") or "").lower() == "cautious":
                cautious_targeted += 1

    print(f"  currently NOT GO              : {len(not_go)}")
    print(f"  → WOULD GO at NORMAL bar      : {would_go}   (score>=38, not active-skip/reduce)")
    print(f"      …of which now in cautious : {cautious_targeted}  ← the mode-fix target set")
    print(f"  → would REDUCE                : {would_reduce}  (score 25-37, or active-REDUCE)")
    print(f"  → still BLOCKED (active-skip) : {blocked_active}  (mode fix can't help these)")
    print(f"  → score too low (<25)         : {score_low}")

    print("\n=== READING THE RESULT ===")
    print("• 'WOULD GO at NORMAL' large + suppression SHADOW → the anchor-aware MIXED")
    print("    mode fix is THE lever; expect GO to multiply once shipped.")
    print("• 'still BLOCKED (active-skip)' large → suppression is the real gate; the mode")
    print("    fix yields little. Decide whether those benches are intended (leave) or")
    print("    need EV-table recalibration (separate lever).")
    print("• 'score too low' large → scoring is starved; threshold/scoring is the lever,")
    print("    not the mode.\n")


if __name__ == "__main__":
    main()
