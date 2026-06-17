#!/usr/bin/env python3
"""
v321g — GATE SCORE × DECISION CROSS-TAB (READ-ONLY)

Answers definitively: "is the confidence score inverted?" by cross-tabulating
confidence_score buckets against the actual decision, and separating the two
HARD VETOES (meta-labeler p_win<0.5, active regime suppression) that override
the score. If GO concentrates at HIGH score buckets → NOT inverted. It also
quantifies the real lever: GO-eligible scores (≥ go_threshold) that were
force-SKIPPED by the meta-labeler.

Decision logic (confidence_gate.py):
  hard veto (p_win<0.5 OR regime-suppress) → SKIP   [overrides score]
  else score ≥ go_threshold (38 normal)    → GO
  else score ≥ reduce_threshold (25 normal)→ REDUCE
  else                                     → SKIP

NOTHING WRITTEN.

Usage:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v321g_gate_crosstab.py
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v321g_gate_crosstab.py --days 30
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

GO_DEFAULT = 38
REDUCE_DEFAULT = 25


def _arg(flag, default, cast):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def main():
    days = _arg("--days", 30, int)
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    log = db.confidence_gate_log

    print(f"\n=== v321g GATE SCORE × DECISION CROSS-TAB (last {days}d) ===\n")

    # matrix[bucket][decision] = count ; plus veto attribution
    matrix = defaultdict(Counter)
    veto = Counter()            # meta_skip / regime_skip / score_skip among SKIPs
    go_eligible_skipped = 0     # score >= GO but decision SKIP (hard veto)
    go_eligible_total = 0
    n = 0
    for r in log.find({"timestamp": {"$gte": iso}},
                      {"_id": 0, "decision": 1, "confidence_score": 1, "reasoning": 1}):
        cs = r.get("confidence_score")
        dec = r.get("decision", "?")
        if cs is None:
            continue
        try:
            cs = float(cs)
        except (TypeError, ValueError):
            continue
        n += 1
        b = int(cs // 10) * 10
        matrix[b][dec] += 1
        if cs >= GO_DEFAULT:
            go_eligible_total += 1
            if dec == "SKIP":
                go_eligible_skipped += 1
        if dec == "SKIP":
            txt = " ".join(str(x) for x in (r.get("reasoning") or []))
            if "NO EDGE" in txt or "< 50%" in txt or "< 50% — NO EDGE" in txt:
                veto["meta_pwin<0.5"] += 1
            elif "Regime suppression (ACTIVE)" in txt:
                veto["regime_suppression"] += 1
            elif "Insufficient confirmation" in txt:
                veto["low_score"] += 1
            else:
                veto["other"] += 1

    if not n:
        print("  no decisions with confidence_score in window.\n")
        return

    print(f"  decisions with score: {n:,}    (GO threshold≈{GO_DEFAULT}, REDUCE≈{REDUCE_DEFAULT}, NORMAL)\n")
    print(f"  {'score':>8} {'GO':>7} {'REDUCE':>7} {'SKIP':>7} {'tot':>7}   GO-rate")
    for b in sorted(matrix):
        go = matrix[b].get("GO", 0)
        rd = matrix[b].get("REDUCE", 0)
        sk = matrix[b].get("SKIP", 0)
        tot = go + rd + sk
        gr = f"{100.0*go/tot:.0f}%" if tot else "-"
        print(f"  {b:>3}-{b+9:<4} {go:>7} {rd:>7} {sk:>7} {tot:>7}   {gr:>6}")

    print(f"\n  → GO-rate should RISE with score if NOT inverted.")
    print(f"\n  GO-eligible (score≥{GO_DEFAULT}) decisions : {go_eligible_total:,}")
    print(f"  …of those, SKIPPED by hard veto     : {go_eligible_skipped:,}  "
          f"({100.0*go_eligible_skipped/go_eligible_total:.0f}%)" if go_eligible_total else "")
    print(f"\n  SKIP attribution:")
    tot_skip = sum(veto.values())
    for k, c in veto.most_common():
        print(f"     {k:<22} {c:>7}  ({100.0*c/tot_skip:.0f}%)")

    print("\n=== READING THE RESULT ===")
    print("• GO-rate climbing left→right across score buckets ⇒ scoring is CORRECT, not inverted.")
    print("• A large 'GO-eligible but SKIPPED by hard veto' ⇒ the meta-labeler p_win<0.5 cut is")
    print("    overriding good scores — THE lever to unblock setups (make it EV-aware, not a")
    print("    flat 0.5 wall). This is independent of detector quality.")
    print("• meta_pwin<0.5 dominating SKIP attribution confirms the same.\n")


if __name__ == "__main__":
    main()
