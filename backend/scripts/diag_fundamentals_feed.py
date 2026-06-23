#!/usr/bin/env python3
"""
diag_fundamentals_feed.py — READ-ONLY root-cause probe for the DARK fundamental
pillar (catalyst ≈ flat/neutral in the TQS edge diags).

The fundamental pillar (15% of TQS) is built in services/tqs/fundamental_quality.py
calculate_score. Two data-fed sub-scores are the suspects:
  • catalyst (30% of the pillar): floors at 40 ("No clear catalyst") UNLESS the
    72h `news_articles` lookup returns rows (then 50-65 by FinBERT sentiment).
    Query: {"symbol": S, "datetime": {"$gte": (now-72h).isoformat()}}
  • earnings (15% of the pillar): needs `earnings_calendar` rows (upcoming <=14d)
    or a recent reported row (is_reported=True, date within 10d) for v390 drift.
    Queries compare a string `date`/`datetime` field with an ISO `$gte/$lte`.

A silent FIELD-TYPE mismatch (BSON Date stored vs ISO-string compared, or a
symbol/casing/format mismatch) makes these return NOTHING even when the
collections are full — which floors catalyst and kills earnings. This diag finds
out WHICH and WHY, by:
  1. DISTRIBUTION of every fundamental sub-score on recently-persisted breakdowns
     (% pinned at the dark defaults: catalyst=40, earnings=60, etc.).
  2. SOURCE COLLECTION health: news_articles + earnings_calendar — row counts,
     the stored TYPE + an example of the date field, recent-window counts.
  3. QUERY REPRODUCTION: runs the EXACT code queries for the top recently-traded
     symbols and reports hit/miss — the decisive test of "is the query matching
     the data?".

NOTHING IS WRITTEN. Run from repo root on the DGX:
  .venv/bin/python backend/scripts/diag_fundamentals_feed.py
  .venv/bin/python backend/scripts/diag_fundamentals_feed.py --symbols 30
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _find_backend():
    for cand in (Path.cwd() / "backend", Path(__file__).resolve().parents[1]):
        if (cand / "services" / "tqs" / "fundamental_quality.py").exists():
            return cand
    print("ERROR: cannot locate backend/ (run from repo root)"); sys.exit(1)


def _load_env(backend_dir):
    env = backend_dir / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _typename(v):
    return type(v).__name__


def _fundamental_distribution(db, days):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cur = db["live_alerts"].find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0, "symbol": 1, "tqs_breakdown": 1},
    ).limit(5000)
    comp_vals = defaultdict(list)
    raw_has_catalyst = Counter()
    n = 0
    for d in cur:
        bd = d.get("tqs_breakdown") or {}
        fund = bd.get("fundamental") or {}
        comps = fund.get("components") or {}
        if not comps:
            continue
        n += 1
        for k, v in comps.items():
            try:
                comp_vals[k].append(float(v))
            except (TypeError, ValueError):
                pass
        rv = fund.get("raw_values") or {}
        raw_has_catalyst[bool(rv.get("has_catalyst"))] += 1

    print("\n" + "=" * 88)
    print(f"1) FUNDAMENTAL sub-score distribution — live_alerts last {days}d "
          f"(n={n} with a fundamental breakdown)")
    print("=" * 88)
    if n == 0:
        print("   no recent live_alerts carry a fundamental breakdown — widen --? or check persistence")
        return
    print(f"   {'sub-score':<16}{'n':>6}{'min':>7}{'med':>7}{'max':>7}{'%@40':>7}{'%@50':>7}{'%@60':>7}{'distinct':>9}")
    for k in sorted(comp_vals):
        vals = comp_vals[k]
        if not vals:
            continue
        vals_sorted = sorted(vals)
        med = vals_sorted[len(vals_sorted) // 2]
        p = lambda t: 100.0 * sum(1 for x in vals if abs(x - t) < 0.5) / len(vals)
        distinct = len(set(round(x, 1) for x in vals))
        print(f"   {k:<16}{len(vals):>6}{min(vals):>7.0f}{med:>7.0f}{max(vals):>7.0f}"
              f"{p(40):>6.0f}%{p(50):>6.0f}%{p(60):>6.0f}%{distinct:>9}")
    print(f"   raw has_catalyst True/False: {dict(raw_has_catalyst)}")
    print("   READ: catalyst pinned @40 = 'No clear catalyst' floor (news lookup returned nothing).")
    print("         earnings pinned @60 = 'no earnings soon' neutral (earnings_calendar lookup empty).")


def _collection_health(db):
    print("\n" + "=" * 88)
    print("2) SOURCE COLLECTION health")
    print("=" * 88)
    now = datetime.now(timezone.utc)

    # ---- news_articles ----
    na = db["news_articles"]
    total = na.estimated_document_count()
    print(f"\n  news_articles: ~{total} docs total")
    sample = list(na.find({}, {"_id": 0}).sort([("$natural", -1)]).limit(3))
    if sample:
        s0 = sample[0]
        dtv = s0.get("datetime")
        print(f"    sample keys      : {sorted(s0.keys())}")
        print(f"    'datetime' field : type={_typename(dtv)}  value={str(dtv)[:40]!r}")
        print(f"    'symbol' field   : {s0.get('symbol')!r}   sentiment={str(s0.get('sentiment'))[:50]!r}")
        # recent-window counts — try BOTH string-ISO and native-datetime comparisons
        cutoff_iso = (now - timedelta(hours=72)).isoformat()
        try:
            c_str = na.count_documents({"datetime": {"$gte": cutoff_iso}})
        except Exception as e:
            c_str = f"err:{e}"
        try:
            c_dt = na.count_documents({"datetime": {"$gte": now - timedelta(hours=72)}})
        except Exception as e:
            c_dt = f"err:{e}"
        print(f"    docs w/ datetime >= 72h-ago  (ISO-string cmp, what CODE uses): {c_str}")
        print(f"    docs w/ datetime >= 72h-ago  (native-datetime cmp)          : {c_dt}")
        if isinstance(c_str, int) and c_str == 0 and isinstance(c_dt, int) and c_dt > 0:
            print("    🔴 MISMATCH: code uses ISO-string compare but field is a native Date "
                  "→ catalyst query returns 0 → catalyst floored. ROOT CAUSE candidate.")
    else:
        print("    🔴 EMPTY — no news_articles docs at all.")

    # ---- earnings_calendar ----
    ec = db["earnings_calendar"]
    total_e = ec.estimated_document_count()
    print(f"\n  earnings_calendar: ~{total_e} docs total")
    sample_e = list(ec.find({}, {"_id": 0}).sort([("$natural", -1)]).limit(3))
    if sample_e:
        e0 = sample_e[0]
        dv = e0.get("date")
        print(f"    sample keys      : {sorted(e0.keys())}")
        print(f"    'date' field     : type={_typename(dv)}  value={str(dv)[:40]!r}")
        try:
            rep = ec.count_documents({"is_reported": True})
        except Exception as e:
            rep = f"err:{e}"
        print(f"    is_reported=True : {rep}   (v390 post-earnings drift needs this)")
        cutoff_up = (now + timedelta(days=14)).isoformat()
        try:
            up = ec.count_documents({"date": {"$gte": now.isoformat(), "$lte": cutoff_up}})
        except Exception as e:
            up = f"err:{e}"
        print(f"    upcoming <=14d   (ISO-string cmp, what CODE uses): {up}")
        try:
            up_dt = ec.count_documents({"date": {"$gte": now, "$lte": now + timedelta(days=14)}})
        except Exception:
            up_dt = "n/a"
        print(f"    upcoming <=14d   (native-datetime cmp)          : {up_dt}")
        if rep == 0:
            print("    🟡 is_reported never True → v390 earnings-drift sub-score is permanently dead.")
    else:
        print("    🔴 EMPTY — no earnings_calendar docs at all.")


def _query_reproduction(db, n_symbols):
    print("\n" + "=" * 88)
    print(f"3) QUERY REPRODUCTION — run the EXACT code queries for top {n_symbols} recently-traded symbols")
    print("=" * 88)
    now = datetime.now(timezone.utc)
    # recently-traded symbols (live_alerts last 14d)
    cutoff = (now - timedelta(days=14)).isoformat()
    syms = Counter()
    for d in db["live_alerts"].find({"created_at": {"$gte": cutoff}}, {"_id": 0, "symbol": 1}).limit(8000):
        s = d.get("symbol")
        if s:
            syms[s] += 1
    top = [s for s, _ in syms.most_common(n_symbols)]
    if not top:
        # fallback to bot_trades
        for d in db["bot_trades"].find({}, {"_id": 0, "symbol": 1}).sort([("$natural", -1)]).limit(2000):
            s = d.get("symbol")
            if s:
                syms[s] += 1
        top = [s for s, _ in syms.most_common(n_symbols)]
    print(f"   probing symbols: {', '.join(top[:n_symbols])}\n")

    news_cut = (now - timedelta(hours=72)).isoformat()
    up_lo, up_hi = now.isoformat(), (now + timedelta(days=14)).isoformat()
    news_hits = earn_hits = recent_rep_hits = 0
    print(f"   {'symbol':<8}{'news72h':>9}{'earn<=14d':>11}{'reported10d':>13}")
    for s in top:
        nh = db["news_articles"].count_documents(
            {"symbol": s, "datetime": {"$gte": news_cut}})
        eh = db["earnings_calendar"].count_documents(
            {"symbol": s, "date": {"$gte": up_lo, "$lte": up_hi}})
        rh = db["earnings_calendar"].count_documents(
            {"symbol": s, "is_reported": True,
             "date": {"$gte": (now - timedelta(days=10)).isoformat(), "$lte": now.isoformat()}})
        news_hits += 1 if nh else 0
        earn_hits += 1 if eh else 0
        recent_rep_hits += 1 if rh else 0
        print(f"   {s:<8}{nh:>9}{eh:>11}{rh:>13}")
    N = max(len(top), 1)
    print(f"\n   HIT RATES across {len(top)} symbols:")
    print(f"     news_articles 72h    : {news_hits}/{N} ({100*news_hits/N:.0f}%)  → drives catalyst")
    print(f"     earnings upcoming14d : {earn_hits}/{N} ({100*earn_hits/N:.0f}%)  → drives earnings proximity")
    print(f"     earnings reported10d : {recent_rep_hits}/{N} ({100*recent_rep_hits/N:.0f}%)  → drives v390 drift")
    if news_hits == 0:
        print("   🔴 0% news hits → catalyst is dark because the live query matches NOTHING for traded")
        print("      symbols. Compare §2's total/window counts: full collection + 0 hits = query/field bug;")
        print("      empty window = stale collector; symbol-format mismatch also possible.")


def main():
    n_symbols = 25
    if "--symbols" in sys.argv:
        try:
            n_symbols = int(sys.argv[sys.argv.index("--symbols") + 1])
        except Exception:
            pass

    backend = _find_backend()
    _load_env(backend)
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]

    print("=" * 88)
    print(f"diag_fundamentals_feed — why is the fundamental/catalyst pillar dark?")
    print(f"  {datetime.now(timezone.utc).isoformat()[:19]}Z   DB={os.environ.get('DB_NAME','tradecommand')}")
    print("=" * 88)

    _fundamental_distribution(db, days=10)
    _collection_health(db)
    _query_reproduction(db, n_symbols)

    print("\n" + "=" * 88)
    print("VERDICT GUIDE:")
    print("  • §1 catalyst pinned @40 + §3 0% news hits + §2 full news_articles → the 72h query")
    print("    field/format is the bug (likely Date-vs-ISO-string or symbol casing). Cheap code fix.")
    print("  • §2 news window count 0 but total>0 → collector stalled (data is stale, not a query bug).")
    print("  • §2 news_articles empty → collector never ran (coverage/infra gap).")
    print("  • earnings: is_reported=0 → v390 drift dead; upcoming 0% → calendar not populated.")
    print("NOTHING WAS WRITTEN.")
    print("=" * 88)


if __name__ == "__main__":
    main()
