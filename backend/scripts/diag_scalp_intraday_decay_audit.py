#!/usr/bin/env python3
"""
diag_scalp_intraday_decay_audit.py  (read-only)
================================================
Answers two product questions before we touch intraday time-decay (D):

  B/#5. Are MFE/MAE stats trustworthy for scalp/intraday trades?
        -> % of trades with hollow mfe_r==mae_r==0 (closed before a
           manage-tick ran) and % missing mfe_pct/mae_pct entirely.

  D.   When scalp/intraday trades are FORCE-CLOSED by the decay timer
        (close_reason ~ scalp_time_decay) or the EOD sweep
        (close_reason ~ eod_auto_close), were they:
          - cut while GREEN and still climbing (MFE >> realized => the
            timer left money on the table), or
          - already underwater / would have stopped out anyway?
        This is the counterfactual the learning loop does NOT compute today.

Also prints, per horizon (scalp/intraday/swing/position), the genuine
close-reason distribution (target / stop / trailing / decay / eod / manual).

Read-only. Connects using MONGO_URL + DB_NAME from backend/.env.

Usage (from repo root):
    source .venv/bin/activate
    curl -s <paste-url> | python3
  or
    python3 backend/scripts/diag_scalp_intraday_decay_audit.py --days 30
"""
from __future__ import annotations
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ── env / db ────────────────────────────────────────────────────────
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


# ── helpers ─────────────────────────────────────────────────────────
HORIZONS = ("scalp", "intraday", "swing", "position", "investment")
ARTIFACT = (
    "consolidated", "reconciled", "stale_pending", "phantom", "symbol_cooldown",
    "guardrail_veto", "operator_flatten_suppression", "intent_already_pending",
    "rejection_cooldown", "broker_rejected", "execution_exception",
    "paper_phase", "simulation_phase", "auto_reaper", "vetoed",
)


def _enum(v):
    return getattr(v, "value", v)


def horizon(t):
    for f in ("timeframe", "trade_type", "scan_tier"):
        v = str(_enum(t.get(f)) or "").lower().strip()
        if v in HORIZONS:
            return v
    return "unknown"


def reason_bucket(cr: str) -> str:
    r = (cr or "").lower()
    if not r:
        return "none"
    if "scalp_time_decay" in r or ("decay" in r and "edge" not in r):
        return "scalp_decay"
    if "eod" in r:
        return "eod_close"
    if "trail" in r:
        return "trailing_stop"
    if "target" in r or "profit" in r or "scale" in r:
        return "target"
    if "stop" in r:
        return "stop_loss"
    if "manual" in r or "operator" in r:
        return "manual"
    return "other"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    _load_env()
    db = _db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    # genuine closed fills only
    cur = db["bot_trades"].find(
        {"closed_at": {"$gte": cutoff}},
        {"_id": 0, "timeframe": 1, "trade_type": 1, "scan_tier": 1, "status": 1,
         "close_reason": 1, "net_pnl": 1, "realized_pnl": 1, "pnl_pct": 1,
         "mfe_pct": 1, "mae_pct": 1, "mfe_r": 1, "mae_r": 1, "exit_price": 1,
         "fill_price": 1, "entry_price": 1, "executed_at": 1, "closed_at": 1,
         "close_at_eod": 1, "symbol": 1},
    )
    trades = []
    for t in cur:
        st = str(_enum(t.get("status")) or "").lower()
        if st in ("open", "pending", "vetoed", "rejected"):
            continue
        if t.get("exit_price") in (None, 0) and t.get("net_pnl") in (None, 0):
            continue
        if any(a in (t.get("close_reason") or "").lower() for a in ARTIFACT):
            continue
        trades.append(t)

    print("\n" + "=" * 70)
    print(f"SCALP/INTRADAY DECAY + MFE/MAE AUDIT — last {args.days}d — {len(trades)} genuine closes")
    print("=" * 70)
    if not trades:
        print("No genuine closed trades in window. (Empty DB or wrong DB_NAME?)")
        return

    # ── per-horizon win/close-reason ────────────────────────────────
    by_h = defaultdict(list)
    for t in trades:
        by_h[horizon(t)].append(t)

    for h in list(HORIZONS) + ["unknown"]:
        rows = by_h.get(h)
        if not rows:
            continue
        n = len(rows)
        pnls = [_f(r.get("net_pnl") or r.get("realized_pnl")) for r in rows]
        wins = sum(1 for p in pnls if p > 0)
        reasons = defaultdict(int)
        for r in rows:
            reasons[reason_bucket(r.get("close_reason"))] += 1
        print(f"\n── {h.upper()}  (n={n}, win={wins/n*100:.0f}%, "
              f"netPnL avg=${sum(pnls)/n:,.0f}, total=${sum(pnls):,.0f})")
        for rb, c in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"     {rb:<14} {c:>4}  ({c/n*100:4.0f}%)")

    # ── MFE/MAE accuracy (scalp + intraday) ─────────────────────────
    si = by_h.get("scalp", []) + by_h.get("intraday", [])
    print("\n" + "-" * 70)
    print(f"MFE/MAE TRUSTWORTHINESS — scalp+intraday (n={len(si)})")
    print("-" * 70)
    if si:
        hollow = sum(1 for t in si if _f(t.get("mfe_r")) == 0 and _f(t.get("mae_r")) == 0)
        miss_pct = sum(1 for t in si if t.get("mfe_pct") in (None,) or t.get("mae_pct") in (None,))
        print(f"  hollow mfe_r==mae_r==0 : {hollow}/{len(si)}  ({hollow/len(si)*100:.0f}%)  "
              f"<- closed before a manage-tick ran")
        print(f"  missing mfe_pct/mae_pct: {miss_pct}/{len(si)}  ({miss_pct/len(si)*100:.0f}%)")
        # hold-time of hollow ones
        holds = []
        for t in si:
            if _f(t.get("mfe_r")) == 0 and _f(t.get("mae_r")) == 0:
                try:
                    e = datetime.fromisoformat(str(t["executed_at"]).replace("Z", "+00:00"))
                    c = datetime.fromisoformat(str(t["closed_at"]).replace("Z", "+00:00"))
                    holds.append((c - e).total_seconds() / 60.0)
                except Exception:
                    pass
        if holds:
            holds.sort()
            print(f"  hollow-trade hold mins : median={holds[len(holds)//2]:.1f}  "
                  f"min={holds[0]:.1f}  max={holds[-1]:.1f}")

    # ── counterfactual: force-closed scalps/intraday ────────────────
    forced = [t for t in si if reason_bucket(t.get("close_reason")) in ("scalp_decay", "eod_close")]
    print("\n" + "-" * 70)
    print(f"FORCE-CLOSED scalp/intraday (decay or EOD) — n={len(forced)}")
    print("-" * 70)
    if forced:
        green = [t for t in forced if _f(t.get("net_pnl") or t.get("realized_pnl")) > 0]
        red = [t for t in forced if _f(t.get("net_pnl") or t.get("realized_pnl")) <= 0]
        # 'left money on table' = was green and MFE notably above realized pnl_pct
        left = []
        for t in forced:
            mfe = _f(t.get("mfe_pct"))
            realized_pct = _f(t.get("pnl_pct"))
            if mfe > 0 and mfe - realized_pct > 0.3:  # >0.3% favorable excursion not captured
                left.append((t.get("symbol"), mfe, realized_pct))
        # 'would have stopped' = mae already worse than a typical stop AND red
        deep = [t for t in red if _f(t.get("mae_pct")) < -0.5]
        print(f"  green at force-close   : {len(green)}/{len(forced)} ({len(green)/len(forced)*100:.0f}%)")
        print(f"  red at force-close     : {len(red)}/{len(forced)} ({len(red)/len(forced)*100:.0f}%)")
        print(f"  LEFT MONEY (MFE>captured+0.3%): {len(left)}  <- timer cut a still-climbing winner")
        print(f"  likely WOULD HAVE STOPPED (red, MAE<-0.5%): {len(deep)}")
        if left[:8]:
            print("    examples (sym, MFE%, captured%):")
            for sym, mfe, rp in left[:8]:
                print(f"      {sym:<6} MFE={mfe:+.2f}%  captured={rp:+.2f}%")
        avg_mfe = sum(_f(t.get("mfe_pct")) for t in forced) / len(forced)
        avg_mae = sum(_f(t.get("mae_pct")) for t in forced) / len(forced)
        print(f"  avg MFE%={avg_mfe:+.2f}   avg MAE%={avg_mae:+.2f}")
        print("\n  VERDICT HINT: if 'LEFT MONEY' is high -> decay/EOD too aggressive;")
        print("                if 'WOULD HAVE STOPPED' dominates -> timer is fine.")

    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
