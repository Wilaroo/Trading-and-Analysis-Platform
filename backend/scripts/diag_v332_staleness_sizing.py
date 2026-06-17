#!/usr/bin/env python3
"""
v332 — STALENESS / TIME-DECAY SIZING (READ-ONLY)

Sizes the time-decay gap the operator flagged: Multi-day / Swing / Position /
Investment trades have NO max-hold / time-stop (order_policy_registry: GTC, exit
only on trail/target/stop). v331b confirmed these tiers DO trade live.

PART A — CLOSED genuine bot-own trades, per tier x HOLD-TIME bucket: n / win% /
  avgR / medR / totR. If win%/avgR fall off a cliff beyond N days, that N is a
  time-stop candidate (dragging trades = dead money).
PART B — currently OPEN/filled holds, per tier: count + age distribution +
  count over a (heuristic) staleness threshold, to size live dead-money risk.

Genuine bot-own only (trade_outcome_hygiene.classify_close + is_adopted_entry).
R = realized_pnl / risk_amount. NOTHING IS WRITTEN.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v332_staleness_sizing.py --days 120
"""
import sys
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median, mean


def _arg(flag, default, cast):
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


def _g(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dt(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# heuristic staleness thresholds (DAYS) for sizing open holds — operator tunes later
STALE_DAYS = {"scalp": 0.5, "intraday": 1, "multi_day": 5, "swing": 15,
              "position": 40, "investment": 90}
TIER_ORDER = ["intraday", "multi_day", "swing", "position", "investment"]
HOLD_BUCKETS = [("<1d", 0, 1), ("1-2d", 1, 2), ("3-5d", 2, 5),
                ("6-10d", 5, 10), (">10d", 10, 1e9)]


def _bucket(days):
    for lab, lo, hi in HOLD_BUCKETS:
        if lo <= days < hi:
            return lab
    return ">10d"


def _stat(rs):
    if not rs:
        return "n=0"
    w = sum(1 for r in rs if r > 0)
    return (f"n={len(rs):<4} win={100*w/len(rs):>3.0f}%  avgR={mean(rs):+.2f}  "
            f"medR={median(rs):+.2f}  totR={sum(rs):+.1f}")


def main():
    days = _arg("--days", 120, int)
    sys.path.insert(0, "backend")
    from services.trade_outcome_hygiene import classify_close, is_adopted_entry
    from services.setup_taxonomy import style_of, canonicalize

    db = _load_db()
    now = datetime.now(timezone.utc)
    since = (now.timestamp() - days * 86400)

    # ---------- PART A: closed genuine trades ----------
    closed = defaultdict(lambda: defaultdict(list))   # tier -> bucket -> [R]
    tier_hold = defaultdict(list)                      # tier -> [hold_days]
    n_genuine = 0
    for t in db.bot_trades.find({"status": "closed"}):
        ca, xa = _dt(_g(t, "created_at", "entry_time", "opened_at")), _dt(_g(t, "closed_at", "exit_time"))
        if not ca or not xa or ca.timestamp() < since:
            continue
        reason = _g(t, "close_reason", "exit_reason") or ""
        eb = _g(t, "entered_by", "entry_source", "source") or ""
        st = _g(t, "setup_type", "strategy") or "unknown"
        genuine, _ = classify_close(
            close_reason=reason, entered_by=str(eb),
            entry_price=_f(_g(t, "entry_price", "fill_price")),
            exit_price=_f(_g(t, "exit_price")), net_pnl=_f(_g(t, "net_pnl", "realized_pnl", "pnl")),
            hold_seconds=(xa - ca).total_seconds(), setup_type=str(st))
        if not genuine or is_adopted_entry(entered_by=str(eb), source=str(_g(t, "source") or ""), close_reason=str(reason)):
            continue
        risk = _f(_g(t, "risk_amount"))
        pnl = _f(_g(t, "realized_pnl", "net_pnl", "pnl"))
        if pnl is None or not risk or risk <= 0:
            continue
        r = pnl / risk
        tier = _g(t, "trade_style") or style_of(canonicalize(st))
        tier = str(getattr(tier, "value", tier))
        hold_days = (xa - ca).total_seconds() / 86400.0
        closed[tier][_bucket(hold_days)].append(r)
        tier_hold[tier].append(hold_days)
        n_genuine += 1

    print(f"\n=== v332 STALENESS / TIME-DECAY SIZING — closed {days}d, {n_genuine} genuine bot-own ===\n")
    print("PART A — CLOSED genuine trades: realized R by TIER x HOLD-TIME bucket")
    print("=" * 78)
    for tier in TIER_ORDER + [t for t in closed if t not in TIER_ORDER]:
        if tier not in closed:
            continue
        allr = [r for b in closed[tier].values() for r in b]
        hd = tier_hold[tier]
        print(f"\n  {tier.upper():<12} overall {_stat(allr)}   holdDays p50={median(hd):.1f} p90={sorted(hd)[int(0.9*len(hd))-1]:.1f} max={max(hd):.1f}")
        for lab, _, _ in HOLD_BUCKETS:
            if closed[tier].get(lab):
                print(f"      {lab:<7} {_stat(closed[tier][lab])}")

    # ---------- PART B: currently open holds ----------
    print("\n\nPART B — CURRENTLY OPEN/filled holds (live dead-money sizing)")
    print("=" * 78)
    open_age = defaultdict(list)
    open_stale = defaultdict(list)   # tier -> [(symbol, age_days)]
    for t in db.bot_trades.find({"status": {"$in": ["open", "filled"]}}):
        ca = _dt(_g(t, "created_at", "entry_time", "opened_at"))
        if not ca:
            continue
        st = _g(t, "setup_type", "strategy") or "unknown"
        tier = _g(t, "trade_style") or style_of(canonicalize(st))
        tier = str(getattr(tier, "value", tier))
        age = (now - ca).total_seconds() / 86400.0
        open_age[tier].append(age)
        if age > STALE_DAYS.get(tier, 5):
            open_stale[tier].append((t.get("symbol", "?"), round(age, 1)))
    if not open_age:
        print("  (no open/filled holds)")
    for tier in TIER_ORDER + [t for t in open_age if t not in TIER_ORDER]:
        if tier not in open_age:
            continue
        ages = sorted(open_age[tier])
        stale = open_stale.get(tier, [])
        print(f"  {tier.upper():<12} open={len(ages):<4} age p50={median(ages):.1f}d "
              f"max={ages[-1]:.1f}d | STALE(>{STALE_DAYS.get(tier)}d)={len(stale)}")
        if stale:
            top = sorted(stale, key=lambda x: -x[1])[:8]
            print("       stale: " + ", ".join(f"{s}({a}d)" for s, a in top))

    print("\n=== READING ===")
    print("• PART A: if a tier's win%/avgR drops sharply beyond a bucket (e.g. swing fine")
    print("    <5d, negative >10d), that boundary is the TIME-STOP candidate for that tier.")
    print("• Winners that resolve FAST + losers that DRAG = classic time-decay → a 'flat if")
    print("    not >=+Xr by day N' rule harvests the dead capital.")
    print("• PART B sizes how much capital is sitting in stale open holds RIGHT NOW.\n")


if __name__ == "__main__":
    main()
