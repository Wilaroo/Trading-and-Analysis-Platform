#!/usr/bin/env python3
"""
diag_tqs_data_health.py — READ-ONLY health of the data feeds behind TQS.

The pillar breakdown showed fundamental/setup/execution are near-constant
(~50) while only technical varies. The hypothesis: those pillars are
DATA-STARVED — they fall to their ~50 defaults because the collections that
feed them are empty/sparse. This checks each feed:

  • symbol_fundamentals_cache  → fundamental pillar (short_interest, float,
    institutional, pe, market_cap, beta). Reports doc count, freshness, and
    per-field coverage %, incl. coverage for the CURRENT open book.
  • learning_stats             → setup pillar's win-rate / EV component.
    Reports how many contexts have enough samples (>=10 medium, >=30 high)
    to escape the 0.5 default.
  • trade_outcomes             → the raw feed that builds learning_stats.
  • earnings_calendar          → fundamental earnings/catalyst TTL feed.

100% read-only. No writes, no restart.

Run (DGX):  .venv/bin/python backend/scripts/diag_tqs_data_health.py
"""
import os
import sys
from collections import Counter
from datetime import datetime, timezone

from pymongo import MongoClient

FUND_FIELDS = [
    "short_interest_percent", "float_shares", "institutional_ownership_percent",
    "pe_ratio", "market_cap", "beta",
]


def pct(n, d):
    return f"{(100*n/d):.0f}%" if d else "—"


def main():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db = MongoClient(url, serverSelectionTimeoutMS=5000)[
        os.environ.get("DB_NAME", "tradecommand")]
    now = datetime.now(timezone.utc)

    # ── 1. Fundamentals cache ─────────────────────────────────────────
    print("══ FUNDAMENTAL pillar feed: symbol_fundamentals_cache ══")
    fc = db["symbol_fundamentals_cache"]
    total = fc.count_documents({})
    print(f"  docs: {total}")
    if total:
        fresh = 0
        field_hits = Counter()
        for d in fc.find({}):
            exp = d.get("expires_at")
            if isinstance(exp, datetime):
                e = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
                if e > now:
                    fresh += 1
            for f in FUND_FIELDS:
                v = d.get(f)
                if v is not None and v != "":
                    field_hits[f] += 1
        print(f"  fresh (not expired): {fresh}/{total} ({pct(fresh, total)})")
        print("  per-field coverage (the scorer needs short_interest/float/institutional):")
        for f in FUND_FIELDS:
            print(f"    {f:<34} {field_hits[f]:>5}/{total}  {pct(field_hits[f], total)}")
        srcs = Counter(d.get("source", "?") for d in fc.find({}, {"source": 1}))
        print(f"  sources: {dict(srcs)}")
    else:
        print("  🔴 EMPTY — fundamental pillar gets ALL DEFAULTS for every symbol.")

    # coverage for the current open book
    open_syms = sorted({d.get("symbol") for d in db["bot_trades"].find(
        {"status": {"$in": ["pending", "open", "partial"]}}, {"symbol": 1})})
    if open_syms:
        have = fc.count_documents({"symbol": {"$in": open_syms}})
        print(f"  open-book coverage: {have}/{len(open_syms)} symbols cached "
              f"({pct(have, len(open_syms))})  {open_syms}")

    # ── 2. Learning stats (setup win-rate component) ──────────────────
    print("\n══ SETUP pillar feed: learning_stats (win-rate / EV) ══")
    ls = db["learning_stats"]
    lt = ls.count_documents({})
    print(f"  contexts: {lt}")
    if lt:
        ge10 = ls.count_documents({"total_trades": {"$gte": 10}})
        ge30 = ls.count_documents({"total_trades": {"$gte": 30}})
        print(f"  >=10 trades (escapes 'low' conf): {ge10}/{lt} ({pct(ge10, lt)})")
        print(f"  >=30 trades (high conf):          {ge30}/{lt} ({pct(ge30, lt)})")
        # per-setup best sample size
        by_setup = {}
        for d in ls.find({}, {"setup_type": 1, "total_trades": 1, "win_rate": 1}):
            st = d.get("setup_type", "?")
            tt = d.get("total_trades", 0) or 0
            if tt > by_setup.get(st, (-1, 0))[0]:
                by_setup[st] = (tt, d.get("win_rate"))
        print("  best sample per setup (setups in your open book matter most):")
        for st in sorted(by_setup):
            tt, wr = by_setup[st]
            flag = "  ← <10: win-rate DEFAULTS to 0.5→score 50" if tt < 10 else ""
            wr_s = f"{wr:.2f}" if isinstance(wr, (int, float)) else "—"
            print(f"    {st:<22} n={tt:<4} win_rate={wr_s}{flag}")
    else:
        print("  🔴 EMPTY — setup win-rate component DEFAULTS to 0.5 (→50) for all.")

    # ── 3. trade_outcomes (raw feed) ──────────────────────────────────
    print("\n══ trade_outcomes (raw feed that builds learning_stats) ══")
    to = db["trade_outcomes"]
    tot = to.count_documents({})
    print(f"  outcomes: {tot}")
    if tot:
        bysetup = Counter(d.get("setup_type", "?")
                          for d in to.find({}, {"setup_type": 1}))
        top = sorted(bysetup.items(), key=lambda x: -x[1])[:12]
        print(f"  by setup_type (top): {dict(top)}")

    # ── 4. earnings_calendar ──────────────────────────────────────────
    print("\n══ earnings_calendar (fundamental TTL / catalyst feed) ══")
    ec = db["earnings_calendar"]
    ect = ec.count_documents({})
    print(f"  rows: {ect}")
    if ect:
        future = ec.count_documents({"date": {"$gte": now.isoformat()}})
        print(f"  future-dated: {future}")

    print("\n══ READ ══")
    print("  Any 🔴 / low coverage above = that pillar is running on defaults,")
    print("  which is why TQS compresses to the C band. Fix = revive the feed,")
    print("  NOT re-weight the pillars (the horizon weighting is by design).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
