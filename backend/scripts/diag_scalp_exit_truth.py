#!/usr/bin/env python3
"""
diag_scalp_exit_truth.py  (read-only)
=====================================
B-step-1: reveal the TRUE exit attribution for scalp/intraday trades.

The audit showed ~65% of scalp closes are lumped under generic reasons
(oca_closed_externally, external_close, operator/emergency flatten) so we
can't tell if a scalp hit its STOP, its TARGET, the decay timer, or EOD —
the learning loop is blind to that. This re-derives the real exit kind:

  - own TARGET / own STOP / TRAIL  (close_reason already says so)
  - TIME_DECAY (scalp decay timer) / EOD
  - MANUAL/OPERATOR (operator/emergency flatten — not strategy-driven)
  - oca_closed_externally / external_close  -> the OCA bracket filled at
    IB; reclassify as TARGET vs STOP by the SIGN of realized P&L
    (pnl>0 = target side, pnl<0 = stop side), and CROSS-CHECK against
    price proximity (exit vs stored stop_price/target_prices) where the
    exit price is available, reporting how often the two agree.

Then per horizon it prints: of the trades that actually RESOLVED on their
own bracket, what % hit TARGET vs STOP (the real scalp edge), vs how many
were force-closed (decay/EOD) or externally interfered with.

Read-only. MONGO_URL + DB_NAME from backend/.env.
Usage:  python3 backend/scripts/diag_scalp_exit_truth.py --days 30
   or:  curl -s <url> | python3 - --days 30
"""
from __future__ import annotations
import argparse
import os
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME", "tradecommand")
    if not url:
        print("ERROR: MONGO_URL not set (and backend/.env not found).")
        sys.exit(1)
    print(f"[db] {name} @ {url.split('@')[-1]}")
    return MongoClient(url)[name]


HORIZONS = ("scalp", "intraday", "swing", "position", "investment")
ARTIFACT = ("consolidated", "stale_pending", "phantom", "symbol_cooldown",
            "guardrail_veto", "intent_already_pending", "rejection_cooldown",
            "broker_rejected", "execution_exception", "paper_phase",
            "simulation_phase", "auto_reaper", "vetoed")


def _enum(v):
    return getattr(v, "value", v)


def horizon(t):
    for f in ("timeframe", "trade_type", "scan_tier"):
        v = str(_enum(t.get(f)) or "").lower().strip()
        if v in HORIZONS:
            return v
    return "unknown"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def exit_kind(t):
    """Return (kind, reclassified_bool)."""
    r = (t.get("close_reason") or "").lower()
    pnl = _f(t.get("net_pnl") or t.get("realized_pnl"))
    notional = abs(_f(t.get("entry_price") or t.get("fill_price")) * _f(t.get("shares")))
    tol = max(1.0, 0.0003 * notional)  # ~0.03% of notional or $1 = "scratch"
    if "target" in r or "scale" in r or "profit" in r:
        return "TARGET_own", False
    if "trail" in r:
        return "TRAIL_own", False
    if "stop" in r:
        return "STOP_own", False
    if "scalp_time_decay" in r or "decay" in r:
        return "TIME_DECAY", False
    if "eod" in r:
        return "EOD", False
    if "operator" in r or "manual" in r or "emergency_flatten" in r or "flatten_all" in r:
        return "MANUAL/OP", False
    if "oca_closed_externally" in r or "external" in r:
        if pnl > tol:
            return "TARGET_inferred", True
        if pnl < -tol:
            return "STOP_inferred", True
        return "SCRATCH_ext", True
    return "OTHER", False


def price_check(t):
    """If exit/stop/target prices present, does pnl-sign agree with nearest price?
    Returns 'agree' / 'disagree' / None."""
    exit_p = _f(t.get("exit_price"))
    stop = _f(t.get("stop_price"))
    tgts = t.get("target_prices") or []
    tgt = _f(tgts[0]) if tgts else 0.0
    if exit_p <= 0 or stop <= 0 or tgt <= 0:
        return None
    near_target = abs(exit_p - tgt) <= abs(exit_p - stop)
    pnl = _f(t.get("net_pnl") or t.get("realized_pnl"))
    sign_target = pnl > 0
    return "agree" if (near_target == sign_target) else "disagree"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    cur = db["bot_trades"].find(
        {"closed_at": {"$gte": cutoff}},
        {"_id": 0, "timeframe": 1, "trade_type": 1, "scan_tier": 1, "status": 1,
         "close_reason": 1, "net_pnl": 1, "realized_pnl": 1, "entry_price": 1,
         "fill_price": 1, "exit_price": 1, "stop_price": 1, "target_prices": 1,
         "shares": 1, "direction": 1, "symbol": 1, "entered_by": 1, "source": 1},
    )
    trades = []
    for t in cur:
        st = str(_enum(t.get("status")) or "").lower()
        if st in ("open", "pending", "vetoed", "rejected"):
            continue
        if t.get("exit_price") in (None, 0) and t.get("net_pnl") in (None, 0) and t.get("realized_pnl") in (None, 0):
            continue
        if any(a in (t.get("close_reason") or "").lower() for a in ARTIFACT):
            continue
        trades.append(t)

    print("\n" + "=" * 72)
    print(f"SCALP/INTRADAY EXIT TRUTH — last {args.days}d — {len(trades)} closes")
    print("=" * 72)
    if not trades:
        print("No genuine closed trades.")
        return

    by_h = defaultdict(list)
    for t in trades:
        by_h[horizon(t)].append(t)

    agree = Counter()
    for h in ("scalp", "intraday"):
        rows = by_h.get(h, [])
        if not rows:
            continue
        kinds = Counter()
        kind_pnl = defaultdict(float)
        for t in rows:
            k, recl = exit_kind(t)
            kinds[k] += 1
            kind_pnl[k] += _f(t.get("net_pnl") or t.get("realized_pnl"))
            if recl:
                pc = price_check(t)
                if pc:
                    agree[pc] += 1
        n = len(rows)
        print(f"\n── {h.upper()}  (n={n})")
        for k, c in kinds.most_common():
            print(f"     {k:<18} {c:>4} ({c/n*100:4.0f}%)   pnl=${kind_pnl[k]:>10,.0f}")

        # bracket-resolved truth
        tp = kinds["TARGET_own"] + kinds["TARGET_inferred"]
        sl = kinds["STOP_own"] + kinds["STOP_inferred"] + kinds["TRAIL_own"]
        resolved = tp + sl
        forced = kinds["TIME_DECAY"] + kinds["EOD"]
        interfered = kinds["MANUAL/OP"]
        print(f"   ── resolved on own bracket: {resolved}/{n} "
              f"({resolved/n*100:.0f}%) — of those TARGET={tp} STOP={sl} "
              f"=> TP-hit rate {tp/resolved*100:.0f}%" if resolved else
              f"   ── resolved on own bracket: 0/{n}")
        print(f"   ── force-closed (decay+EOD): {forced} ({forced/n*100:.0f}%)   "
              f"externally interfered (manual/op): {interfered} ({interfered/n*100:.0f}%)")

    print("\n" + "-" * 72)
    print("RECLASSIFICATION CROSS-CHECK (pnl-sign vs price-proximity, where both known)")
    print("-" * 72)
    tot = sum(agree.values())
    if tot:
        print(f"   agree={agree['agree']}  disagree={agree['disagree']}  "
              f"=> {agree['agree']/tot*100:.0f}% agreement "
              f"({tot} reclassified exits had exit+stop+target prices)")
        print("   (high agreement = pnl-sign reclassification is trustworthy to wire into the live path)")
    else:
        print("   no reclassified exits had all of exit_price+stop_price+target_prices to cross-check.")
        print("   (pnl-sign is still the reliable signal; exit_price often absent on OCA-external closes)")

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
