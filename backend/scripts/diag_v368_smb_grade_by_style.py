#!/usr/bin/env python3
"""diag_v368_smb_grade_by_style.py  (READ-ONLY) — is the scalp SMB grade still mis-calibrated?

AGENTS.md §16 residual: "scalps get inflated full-day SMB B grades that don't reflect intraday
context." v19.34.310 added a timeframe-aware checklist but it is env-gated OFF and only LOOSENS
*swing* thresholds (rvol 2.5->2.0, inplay 1.5->1.2) — it does NOT touch scalp grading. This diag
quantifies the actual situation so we decide: (a) just flip SMB_CHECKLIST_TIMEFRAME_AWARE=true
(helps swings), (b) build scalp-specific tightening, or (c) close as non-issue.

A) ALERTS: smb_grade distribution + avg smb_score_total, grouped by trade_style.
B) BOT_TRADES: realized avg net_pnl / win% / avg-R by trade_style (does the grade predict money?).
NOTHING IS WRITTEN. Usage: .venv/bin/python backend/scripts/diag_v368_smb_grade_by_style.py [--days 30]
"""
import sys
from collections import defaultdict, Counter
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


def _grade_of(d):
    g = d.get("smb_grade")
    if isinstance(g, str) and g.strip():
        return g.strip()
    s = d.get("smb_score_total")
    if s is None:
        s = d.get("smb_5var_score")
    if isinstance(s, (int, float)):
        if s >= 40:
            return "~strong(>=40)"
        if s >= 20:
            return "~mid(20-40)"
        return "~weak(<20)"
    return "?"


def _score_of(d):
    for k in ("smb_score_total", "smb_5var_score"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _r_of(t):
    for k in ("r_multiple", "realized_r", "r_realized"):
        v = t.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    pnl = t.get("net_pnl")
    if pnl is None:
        pnl = t.get("pnl")
    risk = t.get("risk_amount") or t.get("risk")
    if isinstance(pnl, (int, float)) and isinstance(risk, (int, float)) and risk > 0:
        return pnl / risk
    return None


def main():
    days = _arg("--days", 30, int)
    db = _load_db()
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    print(f"\n=== v368 SMB grade by trade_style — last {days}d ===")

    # ── A) ALERTS: grade distribution by style ──────────────────────────────
    coll = "alerts" if db["alerts"].estimated_document_count() else "live_alerts"
    by_style_grade = defaultdict(Counter)
    by_style_score = defaultdict(list)
    n = 0
    for a in db[coll].find(
            {"$or": [{"created_at": {"$gte": cut}}, {"timestamp": {"$gte": cut}}]},
            {"_id": 0, "trade_style": 1, "setup_type": 1, "smb_grade": 1,
             "smb_score_total": 1, "smb_5var_score": 1}):
        style = (a.get("trade_style") or "?").strip().lower() or "?"
        by_style_grade[style][_grade_of(a)] += 1
        s = _score_of(a)
        if s is not None:
            by_style_score[style].append(s)
        n += 1
    print(f"\n--- A) {coll}: {n} alerts; smb_grade distribution + avg score by trade_style ---")
    order = ["scalp", "intraday", "multi_day", "swing", "position", "?"]
    styles = order + [s for s in by_style_grade if s not in order]
    for st in styles:
        if st not in by_style_grade:
            continue
        gc = by_style_grade[st]
        tot = sum(gc.values())
        scores = by_style_score.get(st, [])
        avg = f"{mean(scores):.1f}" if scores else "n/a"
        top = ", ".join(f"{g}:{c}({100*c/tot:.0f}%)" for g, c in gc.most_common(6))
        print(f"  {st:<11} n={tot:<6} avgScore={avg:<6} | {top}")

    # ── B) BOT_TRADES: realized outcome by style ────────────────────────────
    by_style_r = defaultdict(list)
    by_style_win = defaultdict(lambda: [0, 0])  # [wins, scored]
    for t in db["bot_trades"].find(
            {"status": "closed"},
            {"_id": 0, "trade_style": 1, "setup_type": 1, "net_pnl": 1, "pnl": 1,
             "risk_amount": 1, "risk": 1, "r_multiple": 1, "realized_r": 1,
             "closed_at": 1, "created_at": 1}):
        ca = t.get("closed_at") or t.get("created_at")
        if isinstance(ca, str) and ca < cut:
            continue
        style = (t.get("trade_style") or "?").strip().lower() or "?"
        r = _r_of(t)
        pnl = t.get("net_pnl") if t.get("net_pnl") is not None else t.get("pnl")
        if r is not None:
            by_style_r[style].append(max(-3.0, min(3.0, r)))
        if isinstance(pnl, (int, float)):
            by_style_win[style][1] += 1
            by_style_win[style][0] += int(pnl > 0)
    print(f"\n--- B) bot_trades (closed, last {days}d): realized by trade_style ---")
    for st in styles:
        if st not in by_style_r and st not in by_style_win:
            continue
        rs = by_style_r.get(st, [])
        w = by_style_win.get(st, [0, 0])
        wr = f"{100*w[0]/w[1]:.0f}%" if w[1] else "n/a"
        ravg = f"{mean(rs):+.2f}R" if rs else "n/a"
        rmed = f"{median(rs):+.2f}R" if rs else "n/a"
        print(f"  {st:<11} closed={w[1]:<5} win={wr:<5} avgR(winsor±3)={ravg:<8} medR={rmed}")

    print("\n=== READING ===")
    print("• If SCALP alerts cluster at A/B but scalp avgR is ~0 or negative -> grade is INFLATED")
    print("  for scalps -> build scalp-specific checklist tightening (the original §16 concern).")
    print("• If SWING alerts cluster at C/D -> flip SMB_CHECKLIST_TIMEFRAME_AWARE=true (v310 already")
    print("  built it; loosens swing rvol/inplay bars) + validate; cheap, env-reversible.")
    print("• If scalp grades already track scalp outcomes -> close §16 as a non-issue.")
    print("  NOTE: enabling the flag CANNOT change scalp grades (it only touches swing thresholds).\n")


if __name__ == "__main__":
    main()
