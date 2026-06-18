#!/usr/bin/env python3
"""diag_v369_smb_grade_validity.py (READ-ONLY) — does SMB grade predict realized R on TRADED trades?

v368 found grade looks anti-correlated with outcome, but compared all-alerts (grade) vs traded
(outcome) — different populations. This does the RIGOROUS test: bot_trades store smb_score_total +
smb_grade directly (trading_bot_service.py:4806-4808), so we bucket the ACTUAL closed trades by
grade and measure win%/avg-R per bucket — overall and within each trade_style. If higher grade
does NOT yield higher realized R, the SMB scoring is mis-calibrated and worth recalibrating.
NOTHING IS WRITTEN. Usage: .venv/bin/python backend/scripts/diag_v369_smb_grade_validity.py [--days 120]
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


def _bucket(score):
    if not isinstance(score, (int, float)):
        return "?"
    if score >= 40:
        return "4_strong(>=40)"
    if score >= 30:
        return "3_good(30-40)"
    if score >= 20:
        return "2_mid(20-30)"
    return "1_weak(<20)"


def _row(label, rs, wins, scored, cap):
    if scored == 0:
        print(f"    {label:<18} n=0")
        return
    wr = f"{100*wins/scored:.0f}%"
    rr = [max(-cap, min(cap, r)) for r in rs]
    ravg = f"{mean(rr):+.2f}R" if rr else "n/a"
    rmed = f"{median(rs):+.2f}R" if rs else "n/a"
    print(f"    {label:<18} n={scored:<5} win={wr:<5} avgR={ravg:<8} medR={rmed}")


def main():
    days = _arg("--days", 120, int)
    cap = _arg("--winsor", 3.0, float)
    db = _load_db()
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # bucket -> [rs], wins, scored ; and (style,bucket) -> same
    agg = defaultdict(lambda: [[], 0, 0])
    sty = defaultdict(lambda: [[], 0, 0])
    n_total = 0
    for t in db["bot_trades"].find(
            {"status": "closed"},
            {"_id": 0, "trade_style": 1, "smb_score_total": 1, "smb_grade": 1,
             "net_pnl": 1, "pnl": 1, "risk_amount": 1, "risk": 1, "r_multiple": 1,
             "realized_r": 1, "closed_at": 1, "created_at": 1}):
        ca = t.get("closed_at") or t.get("created_at")
        if isinstance(ca, str) and ca < cut:
            continue
        pnl = t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")
        if not isinstance(pnl, (int, float)):
            continue
        n_total += 1
        b = _bucket(t.get("smb_score_total"))
        style = (t.get("trade_style") or "?").strip().lower() or "?"
        r = _r_of(t)
        win = int(pnl > 0)
        for key, store in ((b, agg), ((style, b), sty)):
            store[key][1] += win
            store[key][2] += 1
            if r is not None:
                store[key][0].append(r)

    print(f"\n=== v369 SMB grade VALIDITY on traded population — last {days}d, {n_total} closed trades ===")
    print("Question: does a HIGHER smb_score_total bucket yield HIGHER realized R? If not -> mis-calibrated.\n")

    print("--- OVERALL by score bucket (all styles) ---")
    order = ["4_strong(>=40)", "3_good(30-40)", "2_mid(20-30)", "1_weak(<20)", "?"]
    for b in order:
        if b in agg:
            _row(b, *agg[b], cap)
    # monotonicity verdict
    means = {}
    for b in ("4_strong(>=40)", "3_good(30-40)", "2_mid(20-30)", "1_weak(<20)"):
        if b in agg and agg[b][0]:
            means[b] = mean([max(-cap, min(cap, r)) for r in agg[b][0]])
    print("\n  monotonicity check (avg-R should DECREASE down this list if grade is valid):")
    for b in ("4_strong(>=40)", "3_good(30-40)", "2_mid(20-30)", "1_weak(<20)"):
        if b in means:
            print(f"    {b:<18} avgR={means[b]:+.3f}")
    if len(means) >= 2:
        ks = [b for b in ("4_strong(>=40)", "3_good(30-40)", "2_mid(20-30)", "1_weak(<20)") if b in means]
        vals = [means[k] for k in ks]
        mono = all(vals[i] >= vals[i + 1] - 1e-9 for i in range(len(vals) - 1))
        inv = all(vals[i] <= vals[i + 1] + 1e-9 for i in range(len(vals) - 1))
        verdict = ("VALID (higher grade → higher R)" if mono else
                   "INVERTED (higher grade → LOWER R) — RECALIBRATE" if inv else
                   "NON-MONOTONIC / NOISY — grade weakly predictive")
        print(f"  >>> VERDICT: {verdict}")

    print("\n--- by trade_style × score bucket (focus on cells with n>=10) ---")
    styles = sorted({k[0] for k in sty})
    for st in styles:
        cells = [(b, sty[(st, b)]) for b in order if (st, b) in sty]
        if not cells:
            continue
        print(f"  [{st}]")
        for b, v in cells:
            _row("  " + b, *v, cap)

    print("\n=== READING ===")
    print("• VALID  -> SMB scoring is fine; close §16 (and note scalp-inflation premise was wrong).")
    print("• INVERTED/NOISY on a decent sample (esp. intraday, the largest) -> the grade is mis-")
    print("  calibrated; recalibrate the checklist weights/thresholds against realized R per style.")
    print("• Small-n styles (scalp/swing/position) are directional only — don't over-fit to them.\n")


if __name__ == "__main__":
    main()
