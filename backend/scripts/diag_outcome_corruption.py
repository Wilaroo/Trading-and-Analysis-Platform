#!/usr/bin/env python3
"""
diag_outcome_corruption.py  (READ-ONLY)
=======================================
Confirmation probe for the SETUP-QUALITY TRUTH audit. Nails the EXACT
corruption mechanism before we touch any grading math:

  1. RAW close_reason distribution (overall + for `squeeze`) — is the
     74-100% "non-edge" real EOD/reconcile churn, or a classifier artifact?
  2. CORRUPT-R rows (|r_multiple| > THRESH) — dumps realized_pnl /
     risk_amount / shares / gross_pnl / close_reason / entered_by so we can
     see WHY r exploded (near-zero risk_amount? garbage pnl?).
  3. FIELD POPULATION — what fraction of closed trades actually carry
     gross_pnl / commission / hold_seconds / risk_amount / r_multiple
     (confirms the instrumentation gap).
  4. risk_amount distribution + the count of <=0 / tiny rows that blow R up.
  5. STAT-STORE RECONCILE — strategy_stats vs setup_grade_records side by
     side for key setups (they disagreed: accumulation_entry F vs C).

Mongo only (MONGO_URL / DB_NAME from backend/.env). Writes nothing.
Run from repo root on the DGX:
    .venv/bin/python backend/scripts/diag_outcome_corruption.py --days 30
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env():
    cands = [Path.cwd() / "backend" / ".env", Path.cwd() / ".env"]
    try:
        cands.append(Path(__file__).resolve().parents[1] / ".env")
    except NameError:
        pass
    for c in cands:
        if c.exists():
            for line in c.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _db():
    from pymongo import MongoClient
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name:
        print("ERROR: MONGO_URL / DB_NAME not set.")
        sys.exit(1)
    return MongoClient(url, serverSelectionTimeoutMS=4000)[name]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_of(t):
    r = _num(t.get("r_multiple"))
    if r is not None:
        return r
    pnl, risk = _num(t.get("realized_pnl")), _num(t.get("risk_amount"))
    if pnl is not None and risk and risk > 0:
        return pnl / risk
    return None


def _pcts(vals):
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)
    def p(q):
        return s[min(n - 1, max(0, int(q * n)))]
    return {"n": n, "min": s[0], "p10": p(.1), "p25": p(.25), "p50": p(.5),
            "p75": p(.75), "p90": p(.9), "max": s[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--rthresh", type=float, default=5.0)
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff_str = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"\n{'#'*100}\n#  OUTCOME-DATA CORRUPTION CONFIRMATION   window={args.days}d "
          f"(since {cutoff_str})\n{'#'*100}")

    proj = {"_id": 0, "id": 1, "symbol": 1, "setup_type": 1, "trade_type": 1,
            "entered_by": 1, "realized_pnl": 1, "gross_pnl": 1, "commission": 1,
            "fees": 1, "risk_amount": 1, "r_multiple": 1, "shares": 1,
            "close_reason": 1, "exit_reason": 1, "hold_seconds": 1,
            "executed_at": 1, "closed_at": 1, "learning_only": 1, "entry_context": 1}
    rows = list(db["bot_trades"].find(
        {"status": "closed", "closed_at": {"$gte": cutoff_str}}, proj))
    if not rows:
        rows = list(db["bot_trades"].find(
            {"status": "closed", "closed_at": {"$gte": cutoff_dt}}, proj))
    rows = [t for t in rows if not (t.get("learning_only") is True
            or (t.get("entry_context") or {}).get("learning_only") is True)]
    print(f"\nClosed non-learning trades: {len(rows)}")
    if not rows:
        print("No trades — stop.")
        return

    # ── 1. raw close_reason distribution ────────────────────────────────
    print(f"\n[1] RAW close_reason distribution (overall, top 25)")
    cc = Counter((t.get("close_reason") or t.get("exit_reason") or "<missing>") for t in rows)
    for val, n in cc.most_common(25):
        print(f"    {n:>5}  {val}")
    sq = [t for t in rows if t.get("setup_type") == "squeeze"]
    if sq:
        print(f"\n    close_reason for setup=squeeze (n={len(sq)}, top 15):")
        for val, n in Counter((t.get("close_reason") or t.get("exit_reason") or "<missing>")
                              for t in sq).most_common(15):
            print(f"      {n:>5}  {val}")

    # ── 2. corrupt-R rows ───────────────────────────────────────────────
    print(f"\n[2] CORRUPT-R rows (|r_multiple| > {args.rthresh})")
    bad = []
    for t in rows:
        r = _r_of(t)
        if r is not None and abs(r) > args.rthresh:
            bad.append((r, t))
    bad.sort(key=lambda x: -abs(x[0]))
    print(f"    found {len(bad)} of {len(rows)} ({100.0*len(bad)/len(rows):.1f}%)")
    print(f"    {'r_mult':>9}{'realized':>11}{'risk_amt':>10}{'shares':>8}{'gross':>10}"
          f"  {'setup':<20}{'close_reason':<28}{'entered_by'}")
    for r, t in bad[:40]:
        ra = _num(t.get("risk_amount"))
        gp = _num(t.get("gross_pnl"))
        print(f"    {r:>9.1f}{(_num(t.get('realized_pnl')) or 0):>11.1f}"
              f"{(ra if ra is not None else -1):>10.2f}{(t.get('shares') or 0):>8}"
              f"{(gp if gp is not None else float('nan')):>10.1f}  "
              f"{(t.get('setup_type') or '')[:19]:<20}"
              f"{(t.get('close_reason') or t.get('exit_reason') or '')[:27]:<28}"
              f"{t.get('entered_by') or ''}")

    # ── 3. field population ─────────────────────────────────────────────
    print(f"\n[3] FIELD POPULATION (% of {len(rows)} closed trades with a usable value)")
    for f in ("realized_pnl", "gross_pnl", "commission", "fees", "risk_amount",
              "r_multiple", "hold_seconds", "shares"):
        nn = sum(1 for t in rows if _num(t.get(f)) is not None)
        print(f"    {f:<16}{100.0*nn/len(rows):>6.1f}%   ({nn}/{len(rows)})")

    # ── 4. risk_amount distribution ─────────────────────────────────────
    print(f"\n[4] risk_amount distribution (the R denominator)")
    ras = [_num(t.get("risk_amount")) for t in rows]
    ras = [r for r in ras if r is not None]
    if ras:
        st = _pcts(ras)
        print(f"    n={st['n']}  min={st['min']:.2f}  p10={st['p10']:.2f}  med={st['p50']:.2f}  "
              f"p90={st['p90']:.2f}  max={st['max']:.2f}")
        print(f"    risk_amount <= 0   : {sum(1 for r in ras if r <= 0)}")
        print(f"    0 < risk_amount < 1: {sum(1 for r in ras if 0 < r < 1)}   "
              f"(tiny denominator → R explodes)")
        print(f"    1 <= risk_amount < 10: {sum(1 for r in ras if 1 <= r < 10)}")

    # ── 5. stat-store reconcile ─────────────────────────────────────────
    print(f"\n[5] STAT-STORE RECONCILE — strategy_stats vs setup_grade_records (rolling 30d)")
    keys = ["squeeze", "accumulation_entry", "vwap_fade_long", "vwap_fade_short",
            "pocket_pivot", "gap_fade", "rs_leader_break", "daily_breakout"]
    # rolling rollup from setup_grade_records
    grcut = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    roll = {}
    for r in db["setup_grade_records"].find(
            {"trading_date": {"$gte": grcut}},
            {"_id": 0, "setup_type": 1, "trades_count": 1, "avg_r": 1,
             "win_rate": 1, "total_r": 1}):
        st = r.get("setup_type")
        if not st:
            continue
        d = roll.setdefault(st, {"n": 0, "tr": 0.0, "w": 0.0})
        n = int(r.get("trades_count") or 0)
        d["n"] += n
        d["tr"] += float(r.get("total_r") or (float(r.get("avg_r") or 0) * n))
        d["w"] += float(r.get("win_rate") or 0) * n
    print(f"    {'setup':<22}{'strategy_stats':>26}{'setup_grade_records':>30}")
    print(f"    {'':<22}{'(n / win / avg_r)':>26}{'(n / win / avg_r)':>30}")
    for k in keys:
        ss = db["strategy_stats"].find_one({"strategy": k}) or \
            db["strategy_stats"].find_one({"setup_type": k}) or {}
        ss_n = ss.get("sample_size") or ss.get("total_trades") or 0
        ss_wr = ss.get("win_rate")
        ss_ar = ss.get("avg_r") if ss.get("avg_r") is not None else ss.get("expected_value_r")
        d = roll.get(k)
        if d and d["n"]:
            gr = f"{d['n']} / {d['w']/d['n']*100:.0f}% / {d['tr']/d['n']:+.2f}"
        else:
            gr = "(absent)"
        ssx = (f"{ss_n} / {ss_wr*100:.0f}% / {ss_ar:+.2f}"
               if (ss_n and ss_wr is not None and ss_ar is not None) else "(absent)")
        flag = ""
        if d and d["n"] and ss_n and ss_ar is not None:
            ssign = (ss_ar < 0)
            gsign = (d["tr"]/d["n"] < 0)
            if ssign != gsign:
                flag = "  ⚠ SIGN DISAGREE"
        print(f"    {k:<22}{ssx:>26}{gr:>30}{flag}")

    print(f"\n{'='*100}\nINTERPRETATION GUIDE\n{'='*100}")
    print("• [2] rows with tiny/zero risk_amt but huge r_mult → the corruption is a "
          "bad R DENOMINATOR. Fix = clamp risk_amount + use median R.")
    print("• [1] if close_reason is dominated by eod/reconcile/external → setups rarely "
          "reach their own SL/TP; the 'edge' is closed by time, not thesis.")
    print("• [3] low gross_pnl/commission/hold_seconds % confirms the instrumentation gap.")
    print("• [5] ⚠ SIGN DISAGREE → the two stat stores contradict; the gate and the setup "
          "pillar may be reading different truths.")
    print("\nDone (read-only).")


if __name__ == "__main__":
    main()
