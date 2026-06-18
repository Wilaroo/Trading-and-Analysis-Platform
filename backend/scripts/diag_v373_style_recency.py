#!/usr/bin/env python3
"""diag_v373 (READ-ONLY) — is the recorded bot_trades.trade_style still
collapsing to the generic `trade_2_hold`, or did the trade-create refactor
(opportunity_evaluator line ~1907: trade_style=_resolve_geometry_style(...))
already fix it? Buckets GENUINE trades by created_at recency and reports the
generic-style share per bucket. If recent buckets show ~0% trade_2_hold and
real horizons, the persist fix is already LIVE and no patch is needed.

NOTHING WRITTEN. Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v373_style_recency.py --days 28
"""
import sys
from collections import defaultdict


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


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


_GARBAGE = ("reconcil", "external", "phantom", "operator", "import", "orphan")
_GENERIC = {"trade_2_hold", "", "?", "unknown"}


def _is_genuine(t):
    eb = str(t.get("entered_by") or "").lower()
    if any(g in eb for g in _GARBAGE):
        return False
    if str(t.get("trade_style") or "").lower() == "reconciled":
        return False
    return True


def main():
    from datetime import datetime, timedelta, timezone
    days = _arg("--days", 28, int)
    db = _load_db()
    now = datetime.now(timezone.utc)
    cut = (now - timedelta(days=days)).isoformat()

    # recency buckets (days-ago ranges)
    edges = [0, 3, 7, 14, 21, days]
    edges = sorted(set([e for e in edges if e <= days] + [days]))
    buckets = list(zip(edges[:-1], edges[1:]))  # [(0,3),(3,7),...]

    def bucket_of(iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        ago = (now - dt).total_seconds() / 86400.0
        for lo, hi in buckets:
            if lo <= ago < hi:
                return (lo, hi)
        return None

    agg = defaultdict(lambda: {"n": 0, "generic": 0, "styles": defaultdict(int)})
    for t in db["bot_trades"].find(
            {"status": {"$in": ["closed", "open"]}, "created_at": {"$gte": cut}},
            {"_id": 0, "trade_style": 1, "entered_by": 1, "created_at": 1,
             "setup_type": 1}):
        if not _is_genuine(t):
            continue
        b = bucket_of(t.get("created_at") or "")
        if b is None:
            continue
        st = (t.get("trade_style") or "?").strip().lower()
        a = agg[b]
        a["n"] += 1
        a["styles"][st] += 1
        if st in _GENERIC:
            a["generic"] += 1

    print(f"\n=== v373 trade_style by created_at recency (GENUINE, last {days}d) ===")
    print(f"  {'days-ago':<12}{'n':>5}{'generic%':>10}   style mix (top)")
    for b in buckets:
        a = agg.get(b)
        if not a or a["n"] == 0:
            print(f"  {f'{b[0]}-{b[1]}d':<12}{0:>5}{'--':>10}")
            continue
        gpct = 100 * a["generic"] / a["n"]
        mix = "  ".join(f"{s}:{n}" for s, n in
                        sorted(a["styles"].items(), key=lambda kv: -kv[1])[:6])
        print(f"  {f'{b[0]}-{b[1]}d':<12}{a['n']:>5}{gpct:>9.0f}%   {mix}")

    print("\n=== READING ===")
    print("• If `generic%` (trade_2_hold/empty/unknown) is HIGH in old buckets but")
    print("  ~0% in the 0-3d / 3-7d buckets → the line-1907 _resolve_geometry_style")
    print("  persist fix is already LIVE; the v371 fragmentation was stale history.")
    print("• If recent buckets STILL show high generic% → the persist path is NOT")
    print("  resolving canonically and a patch IS needed.\n")


if __name__ == "__main__":
    main()
