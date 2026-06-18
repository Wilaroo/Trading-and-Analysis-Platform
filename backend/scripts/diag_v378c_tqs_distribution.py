#!/usr/bin/env python3
"""
v378c — TQS SCORE DISTRIBUTION (READ-ONLY). Answers: is TQS>=75 reachable?

smart_filter's borderline band (0.45<=win_rate<0.55) requires quality_score
(= alert['score'], the TQS) >= high_tqs_requirement (75) to PROCEED. If almost
no alert reaches 75, that band is an effective HARD BLOCK on every borderline
setup. This dumps the live TQS distribution from recent alerts.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v378c_tqs_distribution.py --days 5
"""
import sys
from collections import defaultdict
from datetime import datetime, timezone

COLLECTIONS = ["live_scanner_alerts", "live_alerts", "alerts"]
SCORE_FIELDS = ["score", "tqs_score", "tqs_total", "quality_score"]


def _arg(flag, default, cast=str):
    if flag in sys.argv:
        try:
            return cast(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return default
    return default


def _load_db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def _ep(d):
    for k in ("created_at", "ts", "timestamp", "fired_at", "detected_at", "time"):
        v = d.get(k)
        if v in (None, ""):
            continue
        if isinstance(v, (int, float)):
            return float(v) if v < 1e12 else float(v) / 1000.0
        if isinstance(v, datetime):
            return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
    return None


def _score(d):
    for f in SCORE_FIELDS:
        v = d.get(f)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def pctile(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[i]


def report(name, scores):
    if not scores:
        print(f"  {name}: no scored alerts")
        return
    n = len(scores)
    ge = lambda t: sum(1 for x in scores if x >= t)
    print(f"  {name}: n={n}  min={min(scores):.0f}  med={pctile(scores,50):.0f}  "
          f"p90={pctile(scores,90):.0f}  p95={pctile(scores,95):.0f}  "
          f"p99={pctile(scores,99):.0f}  max={max(scores):.0f}")
    print(f"     >=55: {ge(55):>5} ({ge(55)/n*100:4.1f}%)   "
          f">=70: {ge(70):>5} ({ge(70)/n*100:4.1f}%)   "
          f">=75: {ge(75):>5} ({ge(75)/n*100:4.1f}%)   "
          f">=80: {ge(80):>5} ({ge(80)/n*100:4.1f}%)")


def main():
    days = _arg("--days", 5, float)
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    db = _load_db()

    chosen = None
    for c in COLLECTIONS:
        try:
            if db[c].estimated_document_count() > 0:
                chosen = c
                break
        except Exception:
            continue
    if not chosen:
        print("no alert collection found")
        return
    print(f"collection: {chosen}  (last {days}d)\n")

    rows = []
    for d in db[chosen].find({}, {"_id": 0}):
        ep = _ep(d)
        if ep is None or ep >= since:
            rows.append(d)
    scored = [(d, _score(d)) for d in rows]
    all_scores = [s for _, s in scored if s is not None]

    print("=" * 78)
    print("TQS DISTRIBUTION — ALL alerts")
    print("=" * 78)
    report("all", all_scores)
    miss = sum(1 for _, s in scored if s is None)
    print(f"  (alerts with no score field: {miss} of {len(rows)})")

    print("\n" + "=" * 78)
    print("BY trade_style")
    print("=" * 78)
    by = defaultdict(list)
    for d, s in scored:
        if s is not None:
            by[str(d.get("trade_style", "?") or "?")].append(s)
    for style in sorted(by, key=lambda k: -len(by[k])):
        report(style, by[style])

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    if all_scores:
        n = len(all_scores)
        pct75 = sum(1 for x in all_scores if x >= 75) / n * 100
        if pct75 < 2:
            print(f"  TQS>=75 reached by only {pct75:.1f}% of alerts → the borderline-band")
            print(f"  TQS>=75 requirement is an EFFECTIVE HARD BLOCK. SNDK-class (0.45-0.55")
            print(f"  win-rate) setups can essentially NEVER fire. => smart_filter")
            print(f"  high_tqs_requirement (75) is mis-calibrated to the current TQS scale.")
        else:
            print(f"  TQS>=75 reached by {pct75:.1f}% of alerts — threshold is attainable.")


if __name__ == "__main__":
    main()
