#!/usr/bin/env python3
"""
diag_earnings_universe.py — READ-ONLY. Confirms the earnings dark-feed root
causes and double-checks the IB client-12 fundamentals wiring before any patch.

§1  symbol_fundamentals_cache coverage — proves the IB-direct (client-12)
    fundamentals ARE lit (float / short-interest / institutional / DTC / ROE /
    margins). This is the "we already fixed fundamentals from IB" check.
§2  earnings_calendar health — count, distinct symbols, whether ACTUALS are ever
    stored (is_reported / eps_result / eps_surprise_pct — expected 0 per RC2),
    date field type, and how many rows the 2-day prune would already have nuked.
§3  Universe mismatch (RC1) — overlap between the earnings_calendar symbol set
    and the bot's ACTUAL traded/scanner universe (recent live_alerts + open
    bot_trades). Near-zero overlap == the collector is feeding the wrong list.
§4  Schedule reality — the 6 AM ET cron vs "app is usually offline then", and
    whether scheduler_catchup re-runs it on boot.
§5  (optional, --live) hits Finnhub's market-wide date-range call (approach a)
    to tell RC1-wrong-universe apart from Finnhub-plan-restricted. Needs the key.

NOTHING IS WRITTEN.

USAGE (repo root, DGX):
  .venv/bin/python backend/scripts/diag_earnings_universe.py
  .venv/bin/python backend/scripts/diag_earnings_universe.py --live   # also probes Finnhub
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

FUND_FIELDS = [
    "float_shares", "short_interest_percent", "days_to_cover",
    "institutional_ownership_percent", "roe", "net_margin_pct",
    "earnings_catalyst_score",
]
EARN_ACTUAL_FIELDS = ["is_reported", "eps_result", "eps_surprise_pct", "eps_actual"]
EARN_EST_FIELDS = ["eps_estimate", "revenue_estimate", "date"]


def _load_env():
    for cand in ["backend/.env", ".env",
                 os.path.join(os.path.dirname(__file__), "..", ".env")]:
        p = Path(cand)
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _has(v):
    return v not in (None, "", 0, 0.0)


def main():
    _load_env()
    live = "--live" in sys.argv
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"],
                     serverSelectionTimeoutMS=20000)[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)

    print("=" * 96)
    print(f"EARNINGS / FUNDAMENTALS UNIVERSE DIAG  (READ-ONLY)   {now.isoformat()[:19]}Z")
    print("=" * 96)

    # ── §1 symbol_fundamentals_cache (IB client-12 wiring check) ──
    sfc = db["symbol_fundamentals_cache"]
    n_sfc = sfc.estimated_document_count()
    print(f"\n§1  symbol_fundamentals_cache — {n_sfc} docs")
    sample = list(sfc.find({}, {"_id": 0}).limit(4000))
    cov = Counter()
    for d in sample:
        for f in FUND_FIELDS:
            if _has(d.get(f)):
                cov[f] += 1
    n = max(len(sample), 1)
    for f in FUND_FIELDS:
        c = cov.get(f, 0)
        flag = "✅" if c / n >= 0.4 else ("·" if c / n >= 0.1 else "🔴 DARK")
        print(f"    {f:<32} {c:>5}/{n}  ({100*c/n:>4.0f}%)  {flag}")
    print("    → float/short-interest/institutional/DTC/ROE lit == IB client-12 wiring OK.")

    # ── §2 earnings_calendar health ──
    ec = db["earnings_calendar"]
    n_ec = ec.estimated_document_count()
    ec_docs = list(ec.find({}, {"_id": 0}))
    ec_syms = {str(d.get("symbol") or "").upper() for d in ec_docs if d.get("symbol")}
    actual_cov = Counter()
    est_cov = Counter()
    for d in ec_docs:
        for f in EARN_ACTUAL_FIELDS:
            if _has(d.get(f)):
                actual_cov[f] += 1
        for f in EARN_EST_FIELDS:
            if _has(d.get(f)):
                est_cov[f] += 1
    print(f"\n§2  earnings_calendar — {n_ec} docs, {len(ec_syms)} distinct symbols")
    nd = max(len(ec_docs), 1)
    print("    ESTIMATES stored:")
    for f in EARN_EST_FIELDS:
        print(f"      {f:<22} {est_cov.get(f,0):>5}/{nd}  ({100*est_cov.get(f,0)/nd:>4.0f}%)")
    print("    ACTUALS stored (RC2 — drives v390 post-earnings drift):")
    for f in EARN_ACTUAL_FIELDS:
        c = actual_cov.get(f, 0)
        flag = "🔴 NEVER STORED" if c == 0 else "✅"
        print(f"      {f:<22} {c:>5}/{nd}  ({100*c/nd:>4.0f}%)  {flag}")
    # date field type + 2-day prune impact
    dt_field_types = Counter(type(d.get("date")).__name__ for d in ec_docs)
    print(f"    date field python-types: {dict(dt_field_types)}")
    cutoff_2d = (now - timedelta(days=2)).isoformat()
    would_prune = sum(1 for d in ec_docs if str(d.get("date") or "") < cutoff_2d)
    print(f"    rows the 2-day prune (date < now-2d) would delete: {would_prune}/{n_ec}")
    print("    → if ACTUALS=0 AND prune>0, post-earnings drift can NEVER read a reported row.")

    # ── §3 universe mismatch (RC1) ──
    since = (now - timedelta(days=5)).isoformat()
    traded = set()
    for a in db["live_alerts"].find({"created_at": {"$gte": since}}, {"symbol": 1, "_id": 0}):
        if a.get("symbol"):
            traded.add(str(a["symbol"]).upper())
    for t in db["bot_trades"].find(
            {"status": {"$nin": ["closed", "cancelled", "rejected"]}}, {"symbol": 1, "_id": 0}):
        if t.get("symbol"):
            traded.add(str(t["symbol"]).upper())
    overlap = traded & ec_syms
    print(f"\n§3  Universe overlap (RC1)")
    print(f"    bot traded/scanner universe (5d live_alerts + open trades): {len(traded)} symbols")
    print(f"    earnings_calendar symbols                                 : {len(ec_syms)} symbols")
    print(f"    OVERLAP                                                    : {len(overlap)} "
          f"({100*len(overlap)/max(len(traded),1):.0f}% of traded)")
    miss = sorted(traded - ec_syms)
    print(f"    traded names WITHOUT an earnings row (sample): {miss[:25]}")
    print("    → near-zero overlap == collector is feeding symbol_fundamentals_cache[:300], NOT")
    print("      the live-traded universe. (Fix: feed recent live_alerts + dynamic universe.)")

    # ── §4 schedule reality ──
    print(f"\n§4  Schedule")
    print("    refresh_earnings_calendar is cron'd ~06:00 ET (trading_scheduler.py id="
          "'earnings_calendar_refresh').")
    print("    App is typically OFFLINE at 06:00 ET → the job rarely runs. scheduler_catchup")
    print("    (v399) re-runs missed crons on boot ONLY if this job id is in its catch-up set —")
    fresh = ec.find_one({}, sort=[("fetched_at", -1)])
    print(f"    most-recent earnings_calendar.fetched_at: {str((fresh or {}).get('fetched_at'))[:19] or '—'}")

    # ── §5 live Finnhub probe (optional) ──
    print(f"\n§5  Finnhub date-range probe (approach a)")
    if not live:
        print("    skipped (pass --live to run; needs FINNHUB_API_KEY in backend/.env).")
    else:
        key = os.environ.get("FINNHUB_API_KEY")
        if not key:
            print("    🔴 no FINNHUB_API_KEY in env.")
        else:
            import requests
            today = now.date()
            try:
                r = requests.get(
                    "https://finnhub.io/api/v1/calendar/earnings",
                    params={"from": today.isoformat(),
                            "to": (today + timedelta(days=21)).isoformat(),
                            "token": key},
                    timeout=20,
                )
                if r.status_code == 200:
                    rows = (r.json() or {}).get("earningsCalendar", []) or []
                    psyms = {str(x.get("symbol") or "").upper() for x in rows}
                    print(f"    HTTP 200 — date-range returned {len(rows)} rows, {len(psyms)} symbols.")
                    print(f"    overlap with traded universe: {len(traded & psyms)} symbols")
                    if not rows:
                        print("    → empty payload == FREE-TIER RESTRICTED (date-range gives nothing);")
                        print("      the per-symbol fallback over the live universe is the only viable path.")
                    else:
                        print("    → date-range WORKS; RC1 is purely the wrong fallback universe.")
                else:
                    print(f"    HTTP {r.status_code} — likely plan-restricted: {r.text[:120]}")
            except Exception as e:
                print(f"    probe failed: {e}")

    print("\n" + "=" * 96)
    print("VERDICT MAP:  §1 lit → IB fundamentals fine.  §2 ACTUALS=0/prune>0 → RC2 drift dead.")
    print("              §3 low overlap → RC1 wrong universe.  §4 → needs on-boot trigger, not 6am cron.")
    print("=" * 96)


if __name__ == "__main__":
    main()
