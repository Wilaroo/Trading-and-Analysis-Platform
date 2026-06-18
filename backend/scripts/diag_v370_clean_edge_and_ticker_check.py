#!/usr/bin/env python3
"""diag_v370 (READ-ONLY) — genuine-only recent edge by setup/style + scalp-liquidity check on
specific tickers. Excludes the reconciliation/phantom 'garbage' (entered_by reconciled/external/
phantom/operator/import + trade_style=reconciled) per AUDIT_2026-06 genuine-only hygiene.

A) recent GENUINE closed bot_trades grouped by setup_type x trade_style: n / win% / avg net_pnl / avg-R.
B) liquidity/scalp check for --tickers over --tdays days: their alerts' setup_type/trade_style/
   scan_tier + avg_dollar_volume (symbol_adv_cache) + rvol — do they qualify as scalps?
NOTHING WRITTEN. Usage:
  .venv/bin/python backend/scripts/diag_v370_clean_edge_and_ticker_check.py --days 14 --tdays 2 \
      --tickers HON,EWT,IWF,FXI
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median


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


def _is_genuine(t):
    eb = str(t.get("entered_by") or "").lower()
    if any(g in eb for g in _GARBAGE):
        return False
    if str(t.get("trade_style") or "").lower() == "reconciled":
        return False
    return True


def _r_of(t):
    for k in ("r_multiple", "realized_r", "r_realized"):
        v = t.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    pnl = t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")
    risk = t.get("risk_amount") or t.get("risk")
    if isinstance(pnl, (int, float)) and isinstance(risk, (int, float)) and risk > 0:
        return pnl / risk
    return None


def main():
    days = _arg("--days", 14, int)
    tdays = _arg("--tdays", 2, int)
    tickers = [s.strip().upper() for s in _arg("--tickers", "HON,EWT,IWF,FXI", str).split(",") if s.strip()]
    db = _load_db()
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    tcut = (datetime.now(timezone.utc) - timedelta(days=tdays)).isoformat()

    # ── A) genuine recent edge by setup x style ─────────────────────────────
    agg = defaultdict(lambda: {"r": [], "w": 0, "n": 0, "pnl": 0.0})
    excl = 0
    for t in db["bot_trades"].find(
            {"status": "closed"},
            {"_id": 0, "setup_type": 1, "trade_style": 1, "entered_by": 1, "net_pnl": 1,
             "pnl": 1, "risk_amount": 1, "risk": 1, "r_multiple": 1, "realized_r": 1,
             "closed_at": 1, "created_at": 1}):
        ca = t.get("closed_at") or t.get("created_at")
        if isinstance(ca, str) and ca < cut:
            continue
        if not _is_genuine(t):
            excl += 1
            continue
        pnl = t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")
        if not isinstance(pnl, (int, float)):
            continue
        key = f"{t.get('setup_type') or '?'} [{(t.get('trade_style') or '?')}]"
        a = agg[key]
        a["n"] += 1
        a["w"] += int(pnl > 0)
        a["pnl"] += pnl
        r = _r_of(t)
        if r is not None:
            a["r"].append(max(-3.0, min(3.0, r)))
    print(f"\n=== v370 A) GENUINE closed bot_trades, last {days}d (excluded {excl} reconcil/phantom) ===")
    print(f"  {'setup [style]':<34}{'n':>5}{'win%':>6}{'avgR':>8}{'medR':>8}{'netPnl':>10}")
    rows = sorted(agg.items(), key=lambda kv: kv[1]["pnl"])
    for key, a in rows:
        wr = f"{100*a['w']/a['n']:.0f}%" if a["n"] else "n/a"
        ravg = f"{mean(a['r']):+.2f}" if a["r"] else "n/a"
        rmed = f"{median(a['r']):+.2f}" if a["r"] else "n/a"
        print(f"  {key:<34}{a['n']:>5}{wr:>6}{ravg:>8}{rmed:>8}{a['pnl']:>+10.0f}")

    # ── B) scalp-liquidity check on specific tickers ────────────────────────
    print(f"\n=== v370 B) scalp-liquidity check — {tickers} over last {tdays}d ===")
    adv = {}
    for s in tickers:
        c = db["symbol_adv_cache"].find_one({"symbol": s}, {"_id": 0})
        adv[s] = c or {}
    for s in tickers:
        c = adv[s]
        addv = c.get("avg_dollar_volume")
        avol = c.get("avg_volume")
        addv_s = f"${addv/1e6:.1f}M" if isinstance(addv, (int, float)) else "n/a"
        print(f"\n  [{s}] symbol_adv_cache: avg_dollar_volume={addv_s}  avg_volume={avol}  tier={c.get('tier')}")
        # recent alerts for this symbol
        alerts = list(db["live_alerts"].find(
            {"symbol": s, "$or": [{"created_at": {"$gte": tcut}}, {"timestamp": {"$gte": tcut}}]},
            {"_id": 0, "setup_type": 1, "trade_style": 1, "scan_tier": 1, "priority": 1,
             "rvol": 1, "avg_volume": 1, "current_price": 1, "created_at": 1, "timestamp": 1}
        ).sort([("_id", -1)]).limit(20))
        if not alerts:
            print("    (no live_alerts in window)")
        for a in alerts[:12]:
            ts = (a.get("created_at") or a.get("timestamp") or "")[:19]
            print(f"    {ts}  setup={a.get('setup_type'):<16} style={a.get('trade_style') or '?':<10} "
                  f"tier={a.get('scan_tier') or '?':<9} prio={a.get('priority') or '?':<8} "
                  f"rvol={a.get('rvol')}")
        # any closed/open bot_trades for this symbol in window
        trs = list(db["bot_trades"].find(
            {"symbol": s, "$or": [{"created_at": {"$gte": tcut}}, {"closed_at": {"$gte": tcut}}]},
            {"_id": 0, "setup_type": 1, "trade_style": 1, "scan_tier": 1, "entered_by": 1,
             "status": 1, "net_pnl": 1, "pnl": 1}).limit(20))
        for t in trs:
            print(f"    TRADE setup={t.get('setup_type'):<16} style={t.get('trade_style') or '?':<10} "
                  f"tier={t.get('scan_tier') or '?':<9} entered_by={t.get('entered_by')} "
                  f"status={t.get('status')} pnl={t.get('net_pnl') if t.get('net_pnl') is not None else t.get('pnl')}")

    print("\n=== READING ===")
    print("• A) reads GENUINE recent trades only — the real edge by setup/style (not contaminated baseline).")
    print("• B) intraday scalp tier floor is $50M avg-dollar-vol (v297). If a ticker fired a SCALP/intraday")
    print("  setup but its avg_dollar_volume is low / it's an index ETF (EWT/FXI/IWF), question whether the")
    print("  setup or its trade_style classification is right. scan_tier shows which universe it came from.\n")


if __name__ == "__main__":
    main()
