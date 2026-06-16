#!/usr/bin/env python3
"""
v320v — trend_continuation (and multi-timeframe setups) STYLE-RESOLUTION COVERAGE
(READ-ONLY). Pre-work for the P2 "timeframe-aware style resolution" decision.

For trend_continuation trades (open + recent closed), measures HOW the stamped
trade_style was actually pinned and HOW OFTEN resolution would fall through to the
static `SETUP_TO_STYLE["trend_continuation"]="multi_day"` fallback if the explicit
trade_style stamp were absent. That tells us which fix is needed:
  • fallback ~never reached  -> option (a): just guarantee timeframe/trade_style stamping
  • fallback often reached    -> option (c) matters: flip the unsafe multi_day default

Per row it computes (via the SSOT trade_style_classifier.resolve_trade_style):
  stamped         = trade_style as stored
  ctx_only        = resolve WITHOUT explicit trade_style (tiers+timeframe -> else static)
  -> if ctx_only == 'multi_day' the horizon is pinned ONLY by the explicit stamp
     (FRAGILE: if stamping ever fails it carries overnight).
Also dumps the raw context fields actually present (timeframe/scan_tier/tier/
symbol_tier/setup_variant) so we can see what's available to resolve from.

NOTHING is written.

Usage:
  cd ~/Trading-and-Analysis-Platform
  .venv/bin/python backend/scripts/diag_v320v_trend_continuation_timeframe.py [DAYS]   # default 7
  optional 2nd arg: setup substring (default 'trend_continuation')
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

sys.path.insert(0, "backend")
try:
    from services.trade_style_classifier import resolve_trade_style
    from services.setup_taxonomy import canonicalize
except Exception:  # pragma: no cover
    from backend.services.trade_style_classifier import resolve_trade_style
    from backend.services.setup_taxonomy import canonicalize

INTRADAY = {"scalp", "intraday"}
CARRY = {"multi_day", "swing", "position", "investment"}


def _db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


def _entry_dt(row):
    for k in ("executed_at", "created_at", "pre_submit_at"):
        v = row.get(k)
        if isinstance(v, str) and len(v) >= 10:
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    ms = row.get("entry_time_ms")
    if isinstance(ms, (int, float)) and ms > 0:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return None


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 7
    needle = sys.argv[2] if len(sys.argv) > 2 else "trend_continuation"
    db = _db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"\n=== v320v {needle} STYLE-RESOLUTION COVERAGE — last {days}d (+all open) ===\n")

    rows = []
    for t in db.bot_trades.find({}, {"_id": 0}):
        setup = (t.get("setup_type") or "").lower()
        if needle not in canonicalize(setup) and needle not in setup:
            continue
        dt = _entry_dt(t)
        is_open = (t.get("status") or "") == "open"
        if is_open or (dt and dt >= cutoff):
            rows.append(t)

    print(f"matched {len(rows)} {needle} trades\n")
    if not rows:
        print("  (none found)")
        return

    stamped_ct = Counter()
    ctx_ct = Counter()
    tf_ct = Counter()
    fragile = []        # stamped intraday/scalp but ctx_only falls to static multi_day
    mismatch = []       # stamped != ctx_only (and ctx_only not static)
    for t in rows:
        stamped = (t.get("trade_style") or "?").strip().lower()
        stamped_ct[stamped] += 1
        tf_ct[str(t.get("timeframe") or "<none>").lower()] += 1

        ctx_row = {k: t.get(k) for k in
                   ("setup_type", "setup_variant", "scan_tier", "tier", "symbol_tier", "timeframe")}
        ctx_only = resolve_trade_style(ctx_row)
        ctx_ct[ctx_only] += 1

        if stamped in INTRADAY and ctx_only == "multi_day":
            fragile.append((t.get("symbol"), t.get("status"), stamped,
                            str(t.get("timeframe") or "<none>")))
        elif ctx_only not in ("multi_day",) and stamped != ctx_only and stamped in INTRADAY | CARRY:
            mismatch.append((t.get("symbol"), stamped, ctx_only,
                             str(t.get("timeframe") or "<none>")))

    print("STAMPED trade_style:")
    for s, n in stamped_ct.most_common():
        grp = "INTRA" if s in INTRADAY else ("CARRY" if s in CARRY else "?")
        print(f"   {s:<12} {n:>4}  ({grp})")

    print("\nCONTEXT-ONLY resolution (no explicit trade_style; tiers+timeframe -> else static):")
    for s, n in ctx_ct.most_common():
        tag = "  <= STATIC multi_day FALLBACK" if s == "multi_day" else ""
        print(f"   {s:<12} {n:>4}{tag}")

    print("\nTIMEFRAME field values present:")
    for tf, n in tf_ct.most_common(12):
        print(f"   {tf:<14} {n:>4}")

    fallback_n = ctx_ct.get("multi_day", 0)
    print(f"\n>>> RISK METRIC: {fallback_n}/{len(rows)} "
          f"({100.0*fallback_n/len(rows):.0f}%) of {needle} trades have NO context "
          f"(tier/timeframe) that pins a horizon — they fall to the static multi_day\n"
          f"    default if the explicit trade_style stamp is ever missing.")
    print(f"    FRAGILE (stamped intraday/scalp but ctx-only=static multi_day): {len(fragile)}")
    for sym, st, stamped, tf in fragile[:20]:
        print(f"       {sym:<6} {st:<7} stamped={stamped:<9} timeframe={tf}")

    if mismatch:
        print(f"\n  ctx-derivable but stamped differs (informational): {len(mismatch)}")
        for sym, stamped, ctx, tf in mismatch[:15]:
            print(f"       {sym:<6} stamped={stamped:<9} ctx_only={ctx:<9} timeframe={tf}")

    print("\n=== DECISION GUIDE ===")
    print("• RISK METRIC high (most rows fall to static)  -> option (c): the unsafe")
    print("    multi_day fallback is reached often; flip the multi-timeframe default to")
    print("    intraday (EOD-flat) unless timeframe is explicitly daily/weekly.")
    print("• RISK METRIC low + few FRAGILE  -> option (a): explicit stamping is reliable;")
    print("    just guarantee timeframe/trade_style is always set for these setups.")
    print("• If TIMEFRAME values are mostly daily/weekly tokens that DON'T resolve via")
    print("    the classifier -> option (b): map those tokens (extend STYLE_ALIAS).\n")


if __name__ == "__main__":
    main()
