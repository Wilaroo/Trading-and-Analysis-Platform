#!/usr/bin/env python3
"""
v322verify — EV-AWARE META VETO POST-DEPLOY CHECK (READ-ONLY)

Confirms patch_v322 is live and working by reading confidence_gate_log decisions
since a cutoff (default: last 3h) and checking for the NEW reasoning strings the
patch emits, plus the before/after SKIP-attribution shift.

Run AFTER --apply + restart, once the market has produced fresh decisions:
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v322_verify.py
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v322_verify.py --hours 6
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

hours = 3
if "--hours" in sys.argv:
    try:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])
    except Exception:
        hours = 3

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
log = db.confidence_gate_log

print(f"\n=== v322 EV-AWARE META VETO VERIFY — last {hours}h ===\n")

n = 0
dec = Counter()
new_allow = new_skip = old_skip = meta_skip_total = 0
for r in log.find({"timestamp": {"$gte": iso}}, {"_id": 0, "decision": 1, "reasoning": 1}):
    n += 1
    dec[r.get("decision", "?")] += 1
    txt = " ".join(str(x) for x in (r.get("reasoning") or []))
    if "EV-aware ALLOW" in txt:
        new_allow += 1
    if "< EV-floor" in txt:
        new_skip += 1
    if "< 50% — NO EDGE" in txt:        # OLD pre-patch string
        old_skip += 1
    if "NO EDGE" in txt or "< 50%" in txt or "< EV-floor" in txt:
        meta_skip_total += 1

if n == 0:
    print(f"  No gate decisions in the last {hours}h. Market may be closed, or the")
    print(f"  scanner hasn't evaluated yet. Re-run during/after an RTH session.\n")
    sys.exit(0)

print(f"  decisions in window : {n}")
print(f"  GO / REDUCE / SKIP  : {dec.get('GO',0)} / {dec.get('REDUCE',0)} / {dec.get('SKIP',0)}")
print(f"\n  NEW patch strings (proves v322 code path is LIVE):")
print(f"    'EV-aware ALLOW'   : {new_allow}   ← p_win below old 0.50 but ABOVE EV-floor → now allowed")
print(f"    '< EV-floor'       : {new_skip}    ← still skipped, but by EV-floor not flat 0.50")
print(f"    OLD '< 50% NO EDGE': {old_skip}    ← should be 0 post-patch (any >0 = pre-patch rows)")

if new_allow or new_skip:
    print("\n  ✅ v322 IS LIVE — the EV-aware veto is emitting its new reasoning.")
    if new_allow:
        print(f"     {new_allow} setups were ADMITTED that the old flat 0.50 wall would have skipped.")
elif old_skip and not (new_allow or new_skip):
    print("\n  ⚠️ Only OLD strings seen — these may predate the restart. Re-run with more --hours")
    print("     once fresh post-restart decisions accumulate.")
else:
    print("\n  ℹ️ No meta-veto decisions yet in window (no setups hit the p_win<0.55 branch).")

print("\n  Next: once ~a session of data accrues, re-run diag_v321g_gate_crosstab.py —")
print("  expect meta_pwin SKIP share to DROP and GO-eligible-vetoed to fall toward 0.\n")
