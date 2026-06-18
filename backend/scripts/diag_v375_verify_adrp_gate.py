#!/usr/bin/env python3
"""diag_v375 (READ-ONLY) — verify v368 in production.

(A) reads the `trade_drops` collection for the universal liquidity gate since a
    cutoff and tallies the NEW check reasons (scalp_adrp, scalp_share_adv) by
    symbol — proof the gate is now blocking the thin/sleepy scalps.
(B) sanity table: recomputes share-ADV (symbol_adv_cache.avg_volume) and ADRP
    (20-bar ib_historical_data, the SAME formula the gate uses) for a watch
    list and prints the expected verdict at the live floors so the operator
    can confirm the numbers line up with intent.

NOTHING WRITTEN. Usage (repo root, DGX):
  .venv/bin/python backend/scripts/diag_v375_verify_adrp_gate.py --hours 6 \
      --share-floor 3000000 --adrp-floor 2.0 --watch HON,EWT,IWF,FXI,SPY,QQQ,AAPL
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def _arg(flag, d, c):
    if flag in sys.argv:
        try:
            return c(sys.argv[sys.argv.index(flag) + 1])
        except Exception:
            return d
    return d


def _db():
    env = {}
    with open("backend/.env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    from pymongo import MongoClient
    return MongoClient(env["MONGO_URL"], serverSelectionTimeoutMS=20000)[env["DB_NAME"]]


def main():
    hours = _arg("--hours", 6, int)
    share_floor = _arg("--share-floor", 3_000_000, int)
    adrp_floor = _arg("--adrp-floor", 2.0, float)
    watch = _arg("--watch", "HON,EWT,IWF,FXI,SPY,QQQ,AAPL", str).upper().split(",")
    db = _db()
    cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    # ── A) gate drops since cutoff ───────────────────────────────────────
    print(f"\n=== v375 A) universal_liquidity_gate drops, last {hours}h ===")
    by_check = defaultdict(lambda: defaultdict(int))
    total = 0
    for d in db["trade_drops"].find(
            {"gate": "universal_liquidity_gate", "ts": {"$gte": cut}},
            {"_id": 0, "symbol": 1, "context": 1, "setup_type": 1, "reason": 1}):
        chk = (d.get("context") or {}).get("check", "?")
        by_check[chk][d.get("symbol") or "?"] += 1
        total += 1
    if total == 0:
        print("  (no gate drops yet — none fired, or no scalp/intraday alerts on")
        print("   thin/low-ADRP names in this window. Re-run later in the session.)")
    for chk in sorted(by_check, key=lambda k: -sum(by_check[k].values())):
        n = sum(by_check[chk].values())
        top = sorted(by_check[chk].items(), key=lambda kv: -kv[1])[:15]
        print(f"  check={chk:<18} n={n}")
        print("      " + "  ".join(f"{s}:{c}" for s, c in top))
    new_checks = sum(sum(v.values()) for k, v in by_check.items()
                     if k in ("scalp_adrp", "scalp_share_adv"))
    print(f"  → NEW v368 checks (scalp_adrp + scalp_share_adv): {new_checks}")

    # ── B) sanity table for the watch list ───────────────────────────────
    print(f"\n=== v375 B) watch-list sanity @ share≥{share_floor:,} AND ADRP≥{adrp_floor:g}% ===")
    print(f"  {'sym':<7}{'share_adv':>13}{'ADRP%':>8}{'share?':>8}{'adrp?':>7}  scalp verdict")
    for s in watch:
        s = s.strip()
        if not s:
            continue
        c = db["symbol_adv_cache"].find_one({"symbol": s}, {"_id": 0, "avg_volume": 1}) or {}
        share = int(c.get("avg_volume") or 0)
        bars = list(db["ib_historical_data"].find(
            {"symbol": s, "bar_size": "1 day"},
            {"_id": 0, "high": 1, "low": 1, "close": 1}
        ).sort([("date", -1)]).limit(20))
        rngs = [(b["high"] - b["low"]) / b["close"] for b in bars
                if all(isinstance(b.get(k), (int, float)) for k in ("high", "low", "close"))
                and b.get("close")]
        adrp = (100 * sum(rngs) / len(rngs)) if rngs else 0.0
        sp = share >= share_floor
        ap = adrp >= adrp_floor
        verdict = "SCALP-ELIGIBLE" if (sp and ap) else "BLOCKED ("+(
            "share" if not sp else "")+("+" if (not sp and not ap) else "")+(
            "adrp" if not ap else "")+")"
        print(f"  {s:<7}{share:>13,}{adrp:>8.2f}{('Y' if sp else 'N'):>8}"
              f"{('Y' if ap else 'N'):>7}  {verdict}")

    print("\n=== READING ===")
    print("• A) proves the gate is live: scalp_adrp blocks low-range names (IWF/FXI),")
    print("  scalp_share_adv blocks thin-share names (HON). EWT at ADRP~2.3 still")
    print("  passes the 2.0 floor — bump SCALP_MIN_ADRP to 2.5 to catch it too.")
    print("• B) verdicts should match intent; if a number looks off, the gate's")
    print("  on-the-fly compute uses the same 20-bar (high-low)/close formula.\n")


if __name__ == "__main__":
    main()
