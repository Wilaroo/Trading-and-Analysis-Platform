#!/usr/bin/env python3
"""
diag_tqs_b.py — TQS dark-feed CONFIRMATION probe (READ-ONLY)
============================================================

Follow-up to diag_tqs.py. That audit showed three sub-scores PINNED with
stdev≈0 — they are not reading data, they are emitting a hard-coded constant
for the whole book:

  • context.ai_model      → 100% at 35  ("AI model weakly disagrees")  ← PENALTY
  • context.vix           →  99% at 85  ("VIX 18.0 · favorable")
  • fundamental.earnings  → 100% absent ("No earnings within 14d")

This probe proves WHY, straight from the persisted data, so we patch the real
cause and not a guess:

  A) AI: tally the RAW ai_prediction / ai_confidence / ai_agrees_with_direction
     persisted on live_alerts (LiveAlert.to_dict = asdict, so they're all there),
     and cross-tab against the resulting tqs_breakdown.context.ai_model score.
     Hypothesis: the LiveAlert dataclass defaults (ai_prediction="",
     ai_confidence=0.0, ai_agrees_with_direction=False) are NON-None, so an
     ABSENT AI signal falls through the Context pillar to the penalising
     "weakly disagrees" (35) branch instead of the honest neutral 50.

  B) earnings_calendar: collection size, date field TYPE + sample, how many rows
     land in [now, now+14d] (the upcoming gate) and how many are is_reported in
     the last 10d (the post-earnings drift gate). Explains 100% earnings-absent.

  C) VIX: distinct vix_level values seen across the persisted breakdowns and how
     many are != 18.0 (i.e. did a REAL vix ever reach the pillar), best-effort
     scan of likely snapshot collections for a live VIX value.

100% READ-ONLY. No writes, no code edits, no IB calls.

Usage (on the DGX):
    .venv/bin/python diag_tqs_b.py            # last 48h
    .venv/bin/python diag_tqs_b.py --hours 24
"""

import os
import sys
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta


def _parse_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _approx(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def load_alerts(db, hours, cap):
    coll = db["live_alerts"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    proj = {"_id": 0, "symbol": 1, "created_at": 1, "direction": 1,
            "ai_prediction": 1, "ai_confidence": 1,
            "ai_agrees_with_direction": 1, "tqs_breakdown": 1}
    rows = list(coll.find({"created_at": {"$gte": cutoff.isoformat()}}, proj)
                .sort("created_at", -1).limit(cap))
    if not rows:
        raw = list(coll.find({}, proj).sort("created_at", -1).limit(cap))
        rows = [r for r in raw
                if (_parse_dt(r.get("created_at")) or cutoff) >= cutoff]
    return rows


def section_ai(rows):
    print("=" * 92)
    print("  A) AI-MODEL pillar — raw signal vs scored value")
    print("=" * 92)
    pred = Counter()
    conf_zero = conf_pos = 0
    agrees = Counter()
    all_default = 0
    ai_scores = Counter()
    cross = Counter()  # (signal_present, ai_model_score_bucket)
    n = 0
    for r in rows:
        n += 1
        p = r.get("ai_prediction", None)
        c = r.get("ai_confidence", None)
        a = r.get("ai_agrees_with_direction", None)
        pred[repr(p)] += 1
        if _approx(c, 0.0) or c is None:
            conf_zero += 1
        else:
            conf_pos += 1
        agrees[repr(a)] += 1
        is_default = ((p in ("", None)) and (_approx(c, 0.0) or c is None)
                      and (a is False or a is None))
        if is_default:
            all_default += 1
        bd = r.get("tqs_breakdown") or {}
        ctx = (bd.get("context") or {}).get("components") or {}
        if "ai_model" in ctx:
            try:
                sc = round(float(ctx["ai_model"]))
                ai_scores[sc] += 1
                cross[("default" if is_default else "real-signal", sc)] += 1
            except (TypeError, ValueError):
                pass
    print(f"  alerts: {n}")
    print(f"\n  ai_prediction value counts:")
    for k, v in pred.most_common(8):
        print(f"      {k:<14} {v:>6}  ({v/n*100:.1f}%)")
    print(f"\n  ai_confidence:  ==0.0/None: {conf_zero} ({conf_zero/n*100:.1f}%)"
          f"   >0: {conf_pos} ({conf_pos/n*100:.1f}%)")
    print(f"  ai_agrees_with_direction value counts:")
    for k, v in agrees.most_common():
        print(f"      {k:<8} {v:>6}  ({v/n*100:.1f}%)")
    print(f"\n  >>> AI signal ABSENT (prediction='' AND conf=0 AND agrees=False): "
          f"{all_default}/{n} ({all_default/n*100:.1f}%)")
    print(f"\n  resulting context.ai_model score distribution:")
    for k, v in sorted(ai_scores.items()):
        print(f"      score {k:>4}: {v:>6}  ({v/n*100:.1f}%)")
    print(f"\n  cross-tab (signal_state -> ai_model score):")
    for k, v in sorted(cross.items()):
        print(f"      {k[0]:<12} score {k[1]:>4}: {v:>6}")
    print("\n  EXPECTED IF HYPOTHESIS HOLDS: ~all 'default' rows map to score 35")
    print("  (the 'weakly disagrees' branch) — a fabricated PENALTY for missing data.")
    print("  HONEST behaviour would be score 50 (neutral 'No model signal').")


def section_earnings(db):
    print("\n" + "=" * 92)
    print("  B) earnings_calendar — why earnings is 100% absent")
    print("=" * 92)
    try:
        coll = db["earnings_calendar"]
    except Exception as e:
        print(f"  cannot open earnings_calendar: {e}")
        return
    total = coll.count_documents({})
    print(f"  total docs: {total}")
    if total == 0:
        print("  >>> COLLECTION EMPTY — the earnings pillar can never score. "
              "Root cause = no earnings feed/collector populating earnings_calendar.")
        return
    samples = list(coll.find({}, {"_id": 0}).sort("date", -1).limit(5))
    print(f"\n  newest 5 docs (key fields):")
    date_types = Counter()
    for s in samples:
        d = s.get("date")
        date_types[type(d).__name__] += 1
        print(f"      symbol={s.get('symbol'):<8} date={d!r:<34} "
              f"is_reported={s.get('is_reported')} "
              f"eps_result={s.get('eps_result')} "
              f"earnings_score={s.get('earnings_score')}")
    # also sample the type across a wider slice
    for s in coll.find({}, {"_id": 0, "date": 1}).limit(200):
        date_types[type(s.get("date")).__name__] += 1
    print(f"\n  'date' field python types seen: {dict(date_types)}")

    now = datetime.now(timezone.utc)
    in14 = now + timedelta(days=14)
    ago10 = now - timedelta(days=10)
    # ISO-string comparison (matches the pillar's query)
    try:
        up_iso = coll.count_documents(
            {"date": {"$gte": now.isoformat(), "$lte": in14.isoformat()}})
        rep_iso = coll.count_documents(
            {"is_reported": True,
             "date": {"$gte": ago10.isoformat(), "$lte": now.isoformat()}})
        print(f"\n  [ISO-string query, as the pillar runs it]")
        print(f"      upcoming (now..+14d):       {up_iso}")
        print(f"      reported (last 10d):        {rep_iso}")
    except Exception as e:
        print(f"  ISO query failed: {e}")
    # python-side parse, type-agnostic
    up_py = rep_py = unparsed = 0
    for s in coll.find({}, {"_id": 0, "date": 1, "is_reported": 1}).limit(20000):
        dt = _parse_dt(s.get("date"))
        if dt is None:
            unparsed += 1
            continue
        if now <= dt <= in14:
            up_py += 1
        if s.get("is_reported") and ago10 <= dt <= now:
            rep_py += 1
    print(f"\n  [python-parse, type-agnostic, capped 20k scan]")
    print(f"      upcoming (now..+14d):       {up_py}")
    print(f"      reported (last 10d):        {rep_py}")
    print(f"      unparseable 'date' values:  {unparsed}")
    print("\n  READ: if the ISO query returns 0 but python-parse finds rows, the "
          "'date' field is a datetime (not ISO string) and the pillar's string "
          "query silently misses → a fixable query bug. If BOTH are ~0, the feed "
          "is stale/empty (data gap, not a query bug).")


def section_vix(db, rows):
    print("\n" + "=" * 92)
    print("  C) VIX — did a real VIX level ever reach the pillar?")
    print("=" * 92)
    vix_vals = Counter()
    n = 0
    for r in rows:
        bd = r.get("tqs_breakdown") or {}
        rawv = (bd.get("context") or {}).get("raw_values") or {}
        if "vix_level" in rawv:
            n += 1
            try:
                vix_vals[round(float(rawv["vix_level"]), 1)] += 1
            except (TypeError, ValueError):
                pass
    non_default = sum(v for k, v in vix_vals.items() if not _approx(k, 18.0))
    print(f"  alerts carrying vix_level in breakdown: {n}")
    print(f"  distinct vix_level values: {dict(sorted(vix_vals.items()))}")
    print(f"  >>> vix_level != 18.0 (a REAL reading): {non_default}/{n} "
          f"({(non_default/n*100) if n else 0:.1f}%)")
    # best-effort: look for a live VIX in likely snapshot collections
    print("\n  best-effort scan for a live VIX in snapshot collections:")
    for cname in ("ib_live_snapshot", "market_data", "vix_data",
                  "index_quotes", "quotes_snapshot"):
        try:
            if cname not in db.list_collection_names():
                continue
            c = db[cname]
            doc = (c.find_one({"symbol": "VIX"})
                   or c.find_one({"symbol": "^VIX"})
                   or c.find_one({}))
            print(f"      {cname}: {('sample keys=' + str(list(doc.keys())[:12])) if doc else 'empty'}")
        except Exception as e:
            print(f"      {cname}: scan failed ({e})")
    print("\n  READ: if ~0% real readings, VIX never reaches the pillar (push/feed "
          "dark) and an absent VIX is being scored 85 'favorable' — should be "
          "neutral 50 when absent (honest), or wire a real VIX source.")


def main():
    ap = argparse.ArgumentParser(description="TQS dark-feed confirmation probe")
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--cap", type=int, default=8000)
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set.")
        sys.exit(2)
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=4000)[
        os.environ.get("DB_NAME", "tradecommand")]

    rows = load_alerts(db, args.hours, args.cap)
    print(f"  [load] {len(rows)} alerts in last {args.hours}h\n")
    section_ai(rows)
    section_earnings(db)
    section_vix(db, rows)
    print("\n" + "=" * 92)


if __name__ == "__main__":
    main()
