#!/usr/bin/env python3
"""
v322b — EV-AWARE ALLOW → FINAL OUTCOME (READ-ONLY)

Answers: of the decisions the v322 EV-aware veto now ADMITS (reasoning contains
'EV-aware ALLOW'), what is the FINAL gate decision? If they convert to GO →
the unblock produces trades. If they land in REDUCE/SKIP → the binding
constraint has shifted downstream (score threshold / other layers), and we see
exactly where.

Same confidence_gate_log row carries both the 'EV-aware ALLOW' reasoning AND the
final `decision`, so this is an exact join (no fuzzy matching).

Usage:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v322b_allow_outcome.py
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v322b_allow_outcome.py --hours 6
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

GO_THRESH = {"normal": 38, "cautious": 50, "defensive": 60, "aggressive": 28}

hours = 3
if "--hours" in sys.argv:
    try:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])
    except Exception:
        hours = 3

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
log = db.confidence_gate_log

print(f"\n=== v322b EV-AWARE ALLOW → FINAL OUTCOME — last {hours}h ===\n")

allow = []
for r in log.find({"timestamp": {"$gte": iso}},
                  {"_id": 0, "decision": 1, "reasoning": 1, "confidence_score": 1,
                   "trading_mode": 1, "setup_type": 1, "symbol": 1}):
    txt = " ".join(str(x) for x in (r.get("reasoning") or []))
    if "EV-aware ALLOW" in txt:
        r["_txt"] = txt
        allow.append(r)

if not allow:
    print("  No 'EV-aware ALLOW' decisions in window yet. Re-run during/after RTH.\n")
    sys.exit(0)

n = len(allow)
dec = Counter(r.get("decision", "?") for r in allow)
print(f"  EV-aware ALLOW decisions : {n}")
print(f"  → final decision         : "
      + ", ".join(f"{k}={v} ({100.0*v/n:.0f}%)" for k, v in dec.most_common()))

# confidence_score distribution of the admitted rows
scores = sorted(float(r["confidence_score"]) for r in allow if r.get("confidence_score") is not None)
if scores:
    m = len(scores)
    def q(p): return scores[min(int(p * (m - 1)), m - 1)]
    print(f"  confidence_score         : min={scores[0]:.0f} p50={q(.5):.0f} "
          f"max={scores[-1]:.0f}")

# how many ALLOW rows fell just under their mode's GO threshold (→ REDUCE/SKIP)
just_under = 0
for r in allow:
    cs = r.get("confidence_score")
    th = GO_THRESH.get(str(r.get("trading_mode") or "normal").lower(), 38)
    if cs is not None and r.get("decision") != "GO" and cs < th:
        just_under += 1
print(f"  ALLOW-but-not-GO due to score < GO_threshold : {just_under}")

# secondary reason for ALLOW rows that still SKIP
skips = [r for r in allow if r.get("decision") == "SKIP"]
if skips:
    print(f"\n  ALLOW→SKIP secondary reasons ({len(skips)}):")
    sr = Counter()
    for r in skips:
        t = r["_txt"]
        if "Regime suppression (ACTIVE)" in t:
            sr["regime_suppression"] += 1
        elif "Insufficient confirmation" in t or "below" in t.lower():
            sr["low_score"] += 1
        elif "supervisor" in t.lower() or "veto" in t.lower():
            sr["supervisor_veto"] += 1
        else:
            sr["other"] += 1
    for k, c in sr.most_common():
        print(f"     {k:<22} {c}")

# which setups are getting admitted (if stored)
setups = Counter(str(r.get("setup_type") or "?") for r in allow)
if any(k != "?" for k in setups):
    print(f"\n  admitted setups (top): "
          + ", ".join(f"{k}={v}" for k, v in setups.most_common(10) if k != "?"))

print("\n=== READING THE RESULT ===")
print("• ALLOW→GO high  ⇒ the unblock is converting to live (paper) trades. Working.")
print("• ALLOW→REDUCE/SKIP high with 'score < GO_threshold' ⇒ the meta wall is down but")
print("    the SCORE THRESHOLD (30-39 pile-up vs GO=38) is now the binding constraint —")
print("    next lever is threshold calibration, NOT another meta change.")
print("• ALLOW→SKIP via regime_suppression/supervisor ⇒ a different downstream gate; name it.\n")
