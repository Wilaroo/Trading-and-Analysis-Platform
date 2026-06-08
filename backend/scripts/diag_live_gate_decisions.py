#!/usr/bin/env python3
"""
diag_live_gate_decisions.py  (READ-ONLY)
========================================
The meta-labeler is healthy (59.5% clear p_win>=0.50) yet the bot reportedly
takes ~zero trades. The block is in the LIVE confidence gate. This reads the
actual confidence_gate_log + bot_trades to show WHERE live setups die:

  1. Decision distribution (GO / REDUCE / SKIP) overall and last 7 days.
  2. SKIP breakdown:
       - meta-labeler force-skip  ("< 50% — NO EDGE")
       - low confidence           ("Insufficient confirmation")
       - other
  3. trading_mode distribution (are we stuck in CAUTIOUS/DEFENSIVE? those raise
     the GO threshold to 50 / 60).
  4. confidence_score histogram (how close are SKIPs to the GO line?).
  5. regime_score on recent rows.
  6. bot_trades actually placed in last 7 / 30 days.

Writes NOTHING.

Usage:
  cd ~/Trading-and-Analysis-Platform
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_live_gate_decisions.py
"""
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

for _l in open("backend/.env"):
    _l = _l.strip()
    if "=" in _l and not _l.startswith("#"):
        k, v = _l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from pymongo import MongoClient  # noqa: E402

db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

now = datetime.now(timezone.utc)
iso_7d = (now - timedelta(days=7)).isoformat()
iso_30d = (now - timedelta(days=30)).isoformat()

log = db.confidence_gate_log
total = log.count_documents({})
print("=" * 78)
print(f"confidence_gate_log — {total:,} total decisions")
print("=" * 78)

if total == 0:
    print("  ⚠️  EMPTY. The confidence gate has NEVER logged a decision.")
    print("      → The scanner/execution loop may not be calling evaluate() at all,")
    print("        OR nothing reaches the gate (scanner filters reject everything).")
else:
    def dist(match):
        c = Counter()
        for r in log.find(match, {"decision": 1, "_id": 0}):
            c[r.get("decision", "?")] += 1
        return c

    all_d = dist({})
    rec_d = dist({"timestamp": {"$gte": iso_7d}})
    print(f"\nDecision distribution (ALL):  {dict(all_d)}")
    print(f"Decision distribution (7d) :  {dict(rec_d)}")

    # SKIP reason breakdown (last 30d)
    skip_meta = skip_lowconf = skip_other = 0
    mode_counter = Counter()
    regime_scores = []
    score_buckets = Counter()
    n_recent = 0
    for r in log.find({"timestamp": {"$gte": iso_30d}},
                      {"decision": 1, "reasoning": 1, "trading_mode": 1,
                       "regime_score": 1, "confidence_score": 1, "_id": 0}):
        n_recent += 1
        mode_counter[str(r.get("trading_mode", "?"))] += 1
        if r.get("regime_score") is not None:
            try:
                regime_scores.append(float(r["regime_score"]))
            except Exception:
                pass
        cs = r.get("confidence_score")
        if cs is not None:
            try:
                b = int(float(cs) // 10) * 10
                score_buckets[b] += 1
            except Exception:
                pass
        if r.get("decision") == "SKIP":
            reason_txt = " ".join(str(x) for x in (r.get("reasoning") or []))
            if "NO EDGE" in reason_txt or "< 50%" in reason_txt:
                skip_meta += 1
            elif "Insufficient confirmation" in reason_txt:
                skip_lowconf += 1
            else:
                skip_other += 1

    print(f"\n--- Last 30d ({n_recent:,} decisions) ---")
    print(f"SKIP reasons:")
    print(f"  meta-labeler force-skip (p_win<0.50) : {skip_meta}")
    print(f"  low confidence (< go_threshold)      : {skip_lowconf}")
    print(f"  other                                : {skip_other}")

    print(f"\ntrading_mode distribution:")
    for m, c in mode_counter.most_common():
        gt = {"defensive": 60, "cautious": 50, "normal": 38, "aggressive": 28}.get(m.lower(), "?")
        print(f"  {m:<14} {c:>6}   (GO threshold = {gt})")

    if regime_scores:
        regime_scores.sort()
        import statistics
        print(f"\nregime_score: min={regime_scores[0]:.0f} "
              f"median={statistics.median(regime_scores):.0f} "
              f"max={regime_scores[-1]:.0f} mean={statistics.mean(regime_scores):.1f}")

    if score_buckets:
        print(f"\nconfidence_score histogram (bucket → count):")
        for b in sorted(score_buckets):
            bar = "#" * min(60, score_buckets[b] * 60 // max(score_buckets.values()))
            print(f"  {b:>3}-{b+9:<3}: {score_buckets[b]:>6}  {bar}")
        print("  (GO needs >=38 NORMAL / >=50 CAUTIOUS / >=60 DEFENSIVE)")

# bot_trades actually placed
print("\n" + "=" * 78)
print("bot_trades ACTUALLY PLACED")
print("=" * 78)
bt = db.bot_trades
print(f"  total          : {bt.count_documents({}):,}")
for label, iso in [("last 7d", iso_7d), ("last 30d", iso_30d)]:
    n = 0
    for field in ("created_at", "entry_time", "timestamp", "opened_at"):
        n = bt.count_documents({field: {"$gte": iso}})
        if n:
            break
    print(f"  {label:<10}    : {n:,}")

print("\n" + "=" * 78)
print("READ THIS:")
print("  - If SKIPs are mostly 'meta-labeler force-skip' → the 0.50 cut is the block")
print("    (35.8% of setups are positive-EV @2:1 but skipped). EV-aware fix unfreezes.")
print("  - If SKIPs are mostly 'low confidence' AND mode is CAUTIOUS/DEFENSIVE → the")
print("    regime is holding go_threshold at 50-60; setups can't earn enough points.")
print("  - If the log is empty / GO count > 0 but bot_trades ~0 → block is in the")
print("    execution/risk layer downstream of the gate, not the gate itself.")
print("\nDONE — paste this whole block back.")
