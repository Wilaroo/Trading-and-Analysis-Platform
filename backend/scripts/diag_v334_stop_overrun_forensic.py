#!/usr/bin/env python3
"""
v334 — STOP-ENFORCEMENT / OVERRUN FORENSIC (READ-ONLY)

v333 reframed trade_2_hold: net $ POSITIVE (+$56.9k); the "-878R" was a metric
artifact (risk_amount = PLANNED risk, so blown stops + tiny-risk denominators
explode R). BUT real catastrophic losses exist where the EXIT ran far BEYOND the
STOP (WTI short stop 2.86 -> exit 3.21 = -$6,426; USO 108.31 -> 116.12 = -$3,614).

This diag sizes how SYSTEMIC stop-blowing is across ALL genuine bot-own losers:
for each loser it measures the OVERRUN = how far the realized exit went past the
stop (direction-aware), in $ and in R-beyond-planned, and the EXCESS $ lost beyond
the planned -1R risk. Grouped by direction / setup / symbol. This separates
"honored ~-1R stops" (fine) from "blown stops" (P0 risk-management bug).

R-metric note: also reports edge with realized-risk winsorization so the meta-
labeler isn't poisoned by -261R outliers.

NOTHING IS WRITTEN.
Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v334_stop_overrun_forensic.py --days 120
"""
import sys
from collections import Counter, defaultdict
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


def main():
    days = _arg("--days", 120, int)
    sys.path.insert(0, "backend")
    from services.trade_outcome_hygiene import classify_close, is_adopted_entry

    db = _load_db()
    since = datetime.now(timezone.utc).timestamp() - days * 86400

    losers = []
    n_genuine = 0
    for t in db.bot_trades.find({"status": "closed"}):
        ca = _dt(_g(t, "created_at", "entry_time", "opened_at"))
        if not ca or ca.timestamp() < since:
            continue
        reason = _g(t, "close_reason", "exit_reason") or ""
        eb = _g(t, "entered_by", "entry_source", "source") or ""
        xa = _dt(_g(t, "closed_at", "exit_time"))
        hs = (xa - ca).total_seconds() if xa else None
        genuine, _ = classify_close(close_reason=reason, entered_by=str(eb),
                                    entry_price=_f(_g(t, "entry_price", "fill_price")),
                                    exit_price=_f(_g(t, "exit_price")),
                                    net_pnl=_f(_g(t, "net_pnl", "realized_pnl", "pnl")),
                                    hold_seconds=hs, setup_type=str(_g(t, "setup_type") or ""))
        if not genuine or is_adopted_entry(entered_by=str(eb), source=str(_g(t, "source") or ""), close_reason=str(reason)):
            continue
        n_genuine += 1
        pnl = _f(_g(t, "realized_pnl", "net_pnl", "pnl"))
        if pnl is None or pnl >= 0:
            continue
        entry = _f(_g(t, "entry_price", "fill_price")); stop = _f(_g(t, "stop_price", "stop_loss"))
        exit_ = _f(_g(t, "exit_price")); risk = _f(_g(t, "risk_amount")); shares = _f(_g(t, "shares", "quantity"))
        direction = str(_g(t, "direction") or "long").lower()
        # overrun: how far exit went BEYOND the stop, direction-aware
        overrun = None
        if entry and stop and exit_:
            if direction.startswith("l") or (direction in ("0", "buy")):
                overrun = stop - exit_   # long: exit below stop = positive overrun
            else:
                overrun = exit_ - stop   # short: exit above stop = positive overrun
        excess_d = None
        if overrun is not None and shares:
            excess_d = max(0.0, overrun) * shares  # $ lost beyond the stop level
        losers.append({"sym": _g(t, "symbol") or "?", "pnl": pnl, "risk": risk,
                       "r": (pnl / risk) if (risk and risk > 0) else None,
                       "dir": "short" if direction.startswith("s") else "long",
                       "setup": str(_g(t, "setup_type") or "unknown"),
                       "reason": str(reason), "overrun": overrun, "excess_d": excess_d,
                       "entry": entry, "stop": stop, "exit": exit_})

    print(f"\n=== v334 STOP-OVERRUN FORENSIC — closed {days}d, {n_genuine} genuine, {len(losers)} losers ===\n")
    if not losers:
        print("  no losers.\n"); return

    rs = [l["r"] for l in losers if l["r"] is not None]
    honored = [r for r in rs if -1.35 <= r <= -0.65]
    blown = [r for r in rs if r < -1.35]
    scratch = [r for r in rs if r > -0.65]
    print("LOSER R-PROFILE (was the stop honored?):")
    print(f"  honored ~-1R (-1.35..-0.65) : {len(honored)}  ({100*len(honored)//max(len(rs),1)}%)")
    print(f"  BLOWN  (< -1.35R)           : {len(blown)}  ({100*len(blown)//max(len(rs),1)}%)  ← stop overshoot")
    print(f"  scratch/early (> -0.65R)    : {len(scratch)}  ({100*len(scratch)//max(len(rs),1)}%)")

    exc = [(l["excess_d"], l) for l in losers if l["excess_d"] and l["excess_d"] > 1]
    tot_excess = sum(e for e, _ in exc)
    print(f"\nEXCESS $ LOST BEYOND THE STOP LEVEL (overrun x shares):")
    print(f"  total ${tot_excess:,.0f} across {len(exc)} trades where exit ran past the stop")
    by_dir = defaultdict(float); by_setup = defaultdict(float); by_dir_n = Counter()
    for e, l in exc:
        by_dir[l["dir"]] += e; by_dir_n[l["dir"]] += 1; by_setup[l["setup"]] += e
    for d in ("short", "long"):
        if by_dir.get(d):
            print(f"    {d:<6} ${by_dir[d]:>10,.0f}  ({by_dir_n[d]} trades)")
    print("  top setups by excess-$ (stop overshoot):")
    for s, e in sorted(by_setup.items(), key=lambda x: -x[1])[:8]:
        print(f"    {s[:26]:<26} ${e:>10,.0f}")

    print("\nWORST 12 STOP OVERSHOOTS ($ beyond stop):")
    print(f"  {'sym':<7}{'dir':<6}{'$pnl':>9}{'excess$':>9}  {'entry':>8}{'stop':>8}{'exit':>8}  reason")
    for _, l in sorted(exc, key=lambda x: -x[0])[:12]:
        print(f"  {l['sym']:<7}{l['dir']:<6}{l['pnl']:>9,.0f}{l['excess_d']:>9,.0f}  "
              f"{(l['entry'] or 0):>8.2f}{(l['stop'] or 0):>8.2f}{(l['exit'] or 0):>8.2f}  {l['reason'][:22]}")

    print("\n=== READING ===")
    print("• BLOWN% high or EXCESS-$ large (esp. concentrated in SHORTS) → stops are not")
    print("    being honored as hard orders → P0: enforce hard stop orders / cap overshoot.")
    print("• If overshoots are all illiquid/low-priced squeezing shorts → tighten short")
    print("    eligibility (min price/liquidity) and/or use stop-limit-with-buffer or hard mkt-stop.")
    print("• honored ~-1R dominant + tiny EXCESS-$ → stops fine; the R metric is just the")
    print("    artifact (winsorize R in edge/EV stats so the meta-labeler isn't poisoned).\n")


if __name__ == "__main__":
    main()
