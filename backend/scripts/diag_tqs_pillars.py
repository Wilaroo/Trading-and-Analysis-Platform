#!/usr/bin/env python3
"""
diag_tqs_pillars.py — READ-ONLY per-pillar TQS breakdown.

Pinpoints WHICH of the 5 TQS pillars is dragging the score into the C band.
For each pillar (setup / technical / fundamental / context / execution) across
recent `bot_trades`, reports:
  • mean / median / min / max pillar score
  • % of trades where the pillar == 50.0  (the engine's "missing data" default
    — a high % means that pillar is dead weight anchoring the blend to ~55)
  • % of trades where the pillar >= 65     (i.e. could pull the blend toward B)
  • mean weight applied to the pillar
  • mean weighted CONTRIBUTION (score × weight) — how much each pillar actually
    moves the final number.

Helps decide the fix:
  - one/two pillars pinned at 50 → Option C (redistribute weight off dead pillars)
  - all pillars conservatively mid-range → Option A (rescale grade thresholds)

100% read-only. No writes, no restart.

Run (DGX):
    .venv/bin/python backend/scripts/diag_tqs_pillars.py
    DAYS=30 .venv/bin/python backend/scripts/diag_tqs_pillars.py
"""
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

PILLARS = ["setup", "technical", "fundamental", "context", "execution"]


def _num(v):
    """Pillar value may be a plain number or a dict with a 'score' key."""
    if isinstance(v, dict):
        v = v.get("score")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _tqs(doc):
    ec = doc.get("entry_context") or {}
    return ec.get("tqs") or {}


def bar(n, total, width=34):
    if total <= 0:
        return ""
    f = int(round(width * n / total))
    return "█" * f + "·" * (width - f)


def main():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "tradecommand")
    try:
        days = int(os.environ.get("DAYS", "14"))
    except ValueError:
        days = 14

    db = MongoClient(url, serverSelectionTimeoutMS=5000)[db_name]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    docs = list(db.bot_trades.find(
        {"$or": [{"created_at": {"$gte": cutoff}}, {"ts": {"$gte": cutoff}}]}
    ))
    scope = f"last {days} days"
    if not docs:
        docs = list(db.bot_trades.find().sort("_id", -1).limit(500))
        scope = "last 500 trades"

    # only trades that actually captured pillar scores
    docs = [d for d in docs if _tqs(d).get("pillar_scores")]
    print(f"[diag_tqs_pillars] {len(docs)} trades with pillar data · {scope} "
          f"(db={db_name})")
    if not docs:
        print("  (no trades carry entry_context.tqs.pillar_scores)")
        return 0

    scores = defaultdict(list)       # pillar -> [score,...]
    weights = defaultdict(list)      # pillar -> [weight,...]
    at_50 = defaultdict(int)         # pillar -> count == 50
    ge_65 = defaultdict(int)         # pillar -> count >= 65
    n_seen = defaultdict(int)
    finals = []

    for d in docs:
        tqs = _tqs(d)
        ps = tqs.get("pillar_scores") or {}
        w = tqs.get("weights") or {}
        f = _num({"score": tqs.get("score")})
        if f is not None:
            finals.append(f)
        for p in PILLARS:
            s = _num(ps.get(p))
            if s is None:
                continue
            n_seen[p] += 1
            scores[p].append(s)
            if abs(s - 50.0) < 0.05:
                at_50[p] += 1
            if s >= 65:
                ge_65[p] += 1
            wv = w.get(p)
            # weights may be "30%" strings or floats
            if isinstance(wv, str) and wv.endswith("%"):
                try:
                    weights[p].append(float(wv[:-1]) / 100.0)
                except ValueError:
                    pass
            else:
                wn = _num(wv)
                if wn is not None:
                    weights[p].append(wn)

    def stat(lst):
        if not lst:
            return (None, None, None, None)
        s = sorted(lst)
        return (sum(lst) / len(lst), s[len(s) // 2], min(lst), max(lst))

    print("\n  PER-PILLAR (n trades with that pillar shown)")
    print(f"  {'pillar':<12} {'mean':>6} {'med':>6} {'min':>5} {'max':>5} "
          f"{'%==50':>6} {'%>=65':>6} {'wt':>5} {'contrib':>8}")
    print(f"  {'-'*72}")
    for p in PILLARS:
        mean, med, mn, mx = stat(scores[p])
        if mean is None:
            print(f"  {p:<12} (no data)")
            continue
        seen = n_seen[p] or 1
        wmean = (sum(weights[p]) / len(weights[p])) if weights[p] else None
        contrib = (mean * wmean) if (wmean is not None) else None
        print(f"  {p:<12} {mean:>6.1f} {med:>6.1f} {mn:>5.0f} {mx:>5.0f} "
              f"{100*at_50[p]/seen:>5.0f}% {100*ge_65[p]/seen:>5.0f}% "
              f"{(wmean if wmean is not None else 0):>5.2f} "
              f"{(contrib if contrib is not None else 0):>8.1f}")

    # final score recap
    if finals:
        s = sorted(finals)
        print(f"\n  FINAL TQS  n={len(finals)}  mean={sum(finals)/len(finals):.1f}"
              f"  median={s[len(s)//2]:.1f}  min={min(finals):.0f}"
              f"  max={max(finals):.0f}")

    # Verdict hints
    print("\n  READ:")
    dead = [p for p in PILLARS
            if n_seen[p] and at_50[p] / n_seen[p] > 0.5]
    capped = [p for p in PILLARS
              if scores[p] and (sum(scores[p]) / len(scores[p])) < 56
              and (ge_65[p] / (n_seen[p] or 1)) < 0.05]
    if dead:
        print(f"    • Pinned-at-50 (likely missing data, anchoring blend): "
              f"{', '.join(dead)}  → Option C (redistribute weight)")
    if capped:
        print(f"    • Conservative/capped (mean<56, almost never >=65): "
              f"{', '.join(capped)}  → Option A (rescale thresholds) or stretch")
    if not dead and not capped:
        print("    • No single dead pillar — compression is broad → Option A "
              "(rescale thresholds) is the pragmatic win.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
