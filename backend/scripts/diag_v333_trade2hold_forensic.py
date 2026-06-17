#!/usr/bin/env python3
"""
v333 — TRADE_2_HOLD / DEFAULT-STYLE LOSS FORENSIC (READ-ONLY)

v332 surfaced: trade_style 'trade_2_hold' (the LEGACY DEFAULT/fallback style, set
when the classifier assigns nothing — enhanced_scanner:8928, opportunity_evaluator:1737)
holds 528/586 genuine bot-own closes and bleeds avgR -1.66 / totR -878R, yet medR is
only -0.05 → a brutal LEFT TAIL. This diag determines WHETHER that tail is:
  (a) REAL catastrophic losses (blown stops / gaps / slippage) — a P0 risk-mgmt bug, OR
  (b) a CORRUPT risk_amount (tiny denominator) inflating R = realized_pnl/risk_amount.

It dissects the genuine bot-own DEFAULT-style closes by: $ P&L stats, risk_amount health,
winsorized vs dollar-based R, loss attribution by close_reason, setup mix, and the worst
trades verbatim. NOTHING IS WRITTEN.

Usage (repo root, DGX):
  PYTHONPATH=backend .venv/bin/python backend/scripts/diag_v333_trade2hold_forensic.py --days 120
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
    style = _arg("--style", "trade_2_hold", str)
    sys.path.insert(0, "backend")
    from services.trade_outcome_hygiene import classify_close, is_adopted_entry

    db = _load_db()
    since = datetime.now(timezone.utc).timestamp() - days * 86400

    rows = []
    for t in db.bot_trades.find({"status": "closed"}):
        ca = _dt(_g(t, "created_at", "entry_time", "opened_at"))
        if not ca or ca.timestamp() < since:
            continue
        ts = str(_g(t, "trade_style") or "")
        if ts != style:
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
        pnl = _f(_g(t, "realized_pnl", "net_pnl", "pnl"))
        risk = _f(_g(t, "risk_amount"))
        rows.append({
            "sym": _g(t, "symbol") or "?", "pnl": pnl, "risk": risk,
            "r": (pnl / risk) if (pnl is not None and risk and risk > 0) else None,
            "reason": str(reason), "setup": str(_g(t, "setup_type") or "unknown"),
            "entry": _f(_g(t, "entry_price", "fill_price")), "exit": _f(_g(t, "exit_price")),
            "stop": _f(_g(t, "stop_price", "stop_loss")), "shares": _f(_g(t, "shares", "quantity")),
            "hold_min": (hs / 60.0) if hs else None,
        })

    n = len(rows)
    print(f"\n=== v333 '{style}' LOSS FORENSIC — closed {days}d, {n} genuine bot-own ===\n")
    if not n:
        print("  none.\n"); return

    pnls = [r["pnl"] for r in rows if r["pnl"] is not None]
    rs = [r["r"] for r in rows if r["r"] is not None]
    print("DOLLAR P&L:")
    print(f"  total ${sum(pnls):,.0f} | mean ${mean(pnls):,.1f} | median ${median(pnls):,.1f} "
          f"| worst ${min(pnls):,.0f} | best ${max(pnls):,.0f}")
    print(f"  losers {sum(1 for p in pnls if p < 0)}/{len(pnls)}  win% {100*sum(1 for p in pnls if p>0)/len(pnls):.0f}%")

    print("\nR (=pnl/risk_amount):")
    capped = [max(-3.0, min(3.0, r)) for r in rs]
    print(f"  raw    avgR={mean(rs):+.2f} medR={median(rs):+.2f} totR={sum(rs):+.0f}  (n={len(rs)})")
    print(f"  winsor avgR={mean(capped):+.2f} (each R clamped to [-3,+3])  totR={sum(capped):+.0f}")

    print("\nRISK_AMOUNT HEALTH (corrupt denominator inflates R):")
    risks = [r["risk"] for r in rows if r["risk"] is not None]
    miss = sum(1 for r in rows if not r["risk"] or r["risk"] <= 0)
    tiny = sum(1 for r in risks if 0 < r < 5)
    if risks:
        sr = sorted(risks)
        print(f"  have={len(risks)} missing/<=0={miss} tiny(<$5)={tiny} | "
              f"min={sr[0]:.2f} p10={sr[len(sr)//10]:.0f} p50={median(risks):.0f} max={sr[-1]:.0f}")
    # R contribution from tiny-risk rows
    tiny_r = [r["r"] for r in rows if r["r"] is not None and r["risk"] and 0 < r["risk"] < 5]
    if tiny_r:
        print(f"  → {len(tiny_r)} tiny-risk rows contribute totR={sum(tiny_r):+.0f} "
              f"(avgR {mean(tiny_r):+.1f}) — likely R-ARTIFACT, not real loss")

    print("\nLOSS ATTRIBUTION by close_reason ($ summed, losers only):")
    by_reason_d = defaultdict(float); by_reason_n = Counter()
    for r in rows:
        if r["pnl"] is not None and r["pnl"] < 0:
            by_reason_d[r["reason"] or "(blank)"] += r["pnl"]; by_reason_n[r["reason"] or "(blank)"] += 1
    for reason, d in sorted(by_reason_d.items(), key=lambda x: x[1])[:12]:
        print(f"  {reason[:38]:<38} ${d:>11,.0f}  ({by_reason_n[reason]} trades)")

    print("\nSETUP MIX (top by $ bled):")
    by_setup = defaultdict(float); by_setup_n = Counter()
    for r in rows:
        if r["pnl"] is not None:
            by_setup[r["setup"]] += r["pnl"]; by_setup_n[r["setup"]] += 1
    for s, d in sorted(by_setup.items(), key=lambda x: x[1])[:12]:
        print(f"  {s[:26]:<26} ${d:>11,.0f}  ({by_setup_n[s]} trades)")

    print("\nWORST 12 TRADES (verbatim — real blown stop vs artifact):")
    print(f"  {'sym':<7}{'$pnl':>10}{'risk$':>9}{'R':>8}  {'entry':>8}{'stop':>8}{'exit':>8}{'hold':>7}  reason")
    for r in sorted(rows, key=lambda x: (x["pnl"] if x["pnl"] is not None else 0))[:12]:
        rr = f"{r['r']:+.1f}" if r["r"] is not None else "—"
        hm = f"{r['hold_min']:.0f}m" if r["hold_min"] is not None else "—"
        print(f"  {r['sym']:<7}{(r['pnl'] or 0):>10,.0f}{(r['risk'] or 0):>9,.0f}{rr:>8}  "
              f"{(r['entry'] or 0):>8.2f}{(r['stop'] or 0):>8.2f}{(r['exit'] or 0):>8.2f}{hm:>7}  {r['reason'][:24]}")

    print("\n=== READING ===")
    print("• If winsor avgR is mild (≈ medR) but raw avgR is hugely negative → the bleed is")
    print("    a FAT TAIL of a few rows. Check whether those are real (stop << exit, big $) or")
    print("    risk-artifact (tiny risk$ → huge R but small $). The worst-12 + tiny-risk line decide it.")
    print("• If worst trades show exit far BEYOND stop with large $ loss → stops NOT honored (P0).")
    print("• Loss-by-reason concentrated in one reason → that exit path is the culprit.\n")


if __name__ == "__main__":
    main()
