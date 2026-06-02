#!/usr/bin/env python3
"""
diag_tqs_recalibration.py  (READ-ONLY)

Purpose: dump everything needed to RECALIBRATE the TQS grade bands + sizer
multiplier curve now that the EV / Execution / Catalyst pillars are de-pinned
(v216-220). It reports the ACHIEVABLE TQS spread so the A/B/C/D/F bands can be
anchored to real percentile breakpoints instead of guesswork.

Reads two surfaces:
  • live_alerts.tqs_score / tqs_grade / tqs_breakdown  (the scoreable universe)
  • bot_trades.entry_context.tqs.{score,unified_grade} (trades actually taken)

For each it prints:
  • N, min/max/mean/median
  • percentile breakpoints p5/p10/p25/p50/p75/p90/p95
  • a 10-wide score histogram
  • CURRENT-band grade counts (recomputed from score, band-independent)
  • per-trade_style score spread (bands are global, weights differ by style)
  • per-pillar mean/median spread (which pillar still pins)
  • implied sizing distribution at the current A=1.0/B=0.7/C=0.3/D=0.1 curve

100% read-only. Nothing is written. No restart.

Run on the DGX:
    .venv/bin/python backend/scripts/diag_tqs_recalibration.py
    DAYS=3 .venv/bin/python backend/scripts/diag_tqs_recalibration.py
    SINCE_MIN=240 .venv/bin/python backend/scripts/diag_tqs_recalibration.py   # post-restart isolation
"""
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient


# ── CURRENT bands (mirror tqs_engine.py lines 433-446) ──────────────────
CURRENT_BANDS = [(85, "A"), (75, "B+"), (65, "B"), (55, "C+"),
                 (45, "C"), (35, "D"), (0, "F")]
# ── CURRENT sizer curve (mirror opportunity_evaluator._GRADE_MULTIPLIER_DEFAULTS) ──
SIZER = {"A": 1.0, "B": 0.7, "C": 0.3, "D": 0.1}


def grade_from_score(score):
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    for thresh, g in CURRENT_BANDS:
        if s >= thresh:
            return g
    return "F"


def sizer_mult(grade):
    if not grade:
        return SIZER["D"]
    return SIZER.get(grade.strip()[0].upper(), SIZER["D"])


def _load_env():
    url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    for c in ("/app/backend/.env", "./backend/.env", "backend/.env", ".env"):
        if (url and db_name) or not os.path.exists(c):
            continue
        with open(c) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "MONGO_URL" and not url:
                    url = v
                elif k == "DB_NAME" and not db_name:
                    db_name = v
    return url or "mongodb://localhost:27017", db_name or "tradecommand"


def _pctile(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    idx = int(round((len(sorted_vals) - 1) * q))
    return sorted_vals[max(0, min(idx, len(sorted_vals) - 1))]


def bar(n, total, width=38):
    if total <= 0:
        return ""
    filled = int(round(width * n / total))
    return "#" * filled + "." * (width - filled)


def _report(label, scores, grades_persisted, by_style, by_pillar):
    print("\n" + "=" * 74)
    print(f"  {label}   N={len(scores)}")
    print("=" * 74)
    if not scores:
        print("  (no scored rows)")
        return
    s = sorted(scores)
    print(f"  score: mean={statistics.mean(s):.1f} median={statistics.median(s):.1f} "
          f"min={s[0]:.0f} max={s[-1]:.0f} stdev={statistics.pstdev(s):.1f}")
    print("  percentiles: " + "  ".join(
        f"p{int(q*100)}={_pctile(s, q):.0f}"
        for q in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)))

    # score histogram
    buckets = defaultdict(int)
    for v in s:
        buckets[int(v // 5) * 5] += 1
    print("  histogram (5-wide):")
    for b in range(0, 100, 5):
        n = buckets.get(b, 0)
        if n:
            print(f"    {b:>2}-{b+4:<2} {n:>5}  {bar(n, len(s))}")

    # current-band grade distribution (recomputed from score)
    print("\n  GRADE @ CURRENT BANDS (recomputed from score):")
    gc = Counter(grade_from_score(v) for v in s)
    for _, g in CURRENT_BANDS:
        if gc.get(g):
            print(f"    {g:<3} {gc[g]:>5}  {bar(gc[g], len(s))}  {100*gc[g]/len(s):.0f}%")

    # persisted grade (what the bot actually stamped)
    if grades_persisted:
        pc = Counter(grades_persisted)
        print("  PERSISTED grade (what bot stamped): " +
              ", ".join(f"{k}={v}" for k, v in pc.most_common()))

    # implied sizing distribution
    print("\n  IMPLIED SIZING @ current curve (A=1.0 B=0.7 C=0.3 D=0.1):")
    mults = [sizer_mult(grade_from_score(v)) for v in s]
    mc = Counter(f"{m:.1f}x" for m in mults)
    for k, v in sorted(mc.items(), reverse=True):
        print(f"    {k:<5} {v:>5}  {bar(v, len(s))}  {100*v/len(s):.0f}%")
    print(f"    mean size multiplier = {statistics.mean(mults):.2f}x")

    # per-style spread
    if by_style:
        print("\n  PER-STYLE score spread (bands are global; weights differ):")
        for style, vals in sorted(by_style.items(), key=lambda kv: -len(kv[1])):
            if len(vals) >= 2:
                vs = sorted(vals)
                print(f"    {style:<12} n={len(vs):<4} mean={statistics.mean(vs):.1f} "
                      f"p50={statistics.median(vs):.0f} p90={_pctile(vs,0.9):.0f} max={vs[-1]:.0f}")

    # per-pillar spread
    if by_pillar:
        print("\n  PER-PILLAR score spread (which pillar still pins?):")
        for p in ("setup", "technical", "fundamental", "context", "execution"):
            vals = by_pillar.get(p) or []
            if vals:
                vs = sorted(vals)
                print(f"    {p:<12} n={len(vs):<4} mean={statistics.mean(vs):.1f} "
                      f"median={statistics.median(vs):.0f} min={vs[0]:.0f} max={vs[-1]:.0f}")


def main():
    url, db_name = _load_env()
    db = MongoClient(url, serverSelectionTimeoutMS=5000)[db_name]
    now = datetime.now(timezone.utc)
    since_min = int(os.environ.get("SINCE_MIN", "0") or 0)
    days = int(os.environ.get("DAYS", "3") or 3)
    if since_min > 0:
        cutoff = (now - timedelta(minutes=since_min)).isoformat()
        win = f"last {since_min} min"
    else:
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        win = f"last {days} days (>= {cutoff})"
    print(f"DB={db_name}   window={win}")

    # ── live_alerts ──
    rows = list(db["live_alerts"].find({"created_at": {"$gte": cutoff}}))
    if not rows:
        rows = list(db["live_alerts"].find().sort("created_at", -1).limit(500))
        print("(alerts window empty — fell back to most-recent 500)")
    a_scores, a_grades, a_style, a_pillar = [], [], defaultdict(list), defaultdict(list)
    for r in rows:
        sc = r.get("tqs_score")
        try:
            sc = float(sc or 0)
        except (TypeError, ValueError):
            sc = 0.0
        if sc > 0:
            a_scores.append(sc)
            a_style[r.get("trade_style") or r.get("scan_tier") or "?"].append(sc)
        if r.get("tqs_grade"):
            a_grades.append(r["tqs_grade"])
        bd = r.get("tqs_breakdown") or {}
        for p in ("setup", "technical", "fundamental", "context", "execution"):
            ps = (bd.get(p) or {}).get("score")
            if isinstance(ps, (int, float)):
                a_pillar[p].append(ps)
    _report("LIVE_ALERTS (scoreable universe)", a_scores, a_grades, a_style, a_pillar)

    # ── bot_trades ──
    tq = {"$or": [{"created_at": {"$gte": cutoff}}, {"ts": {"$gte": cutoff}}]}
    docs = list(db["bot_trades"].find(tq))
    if not docs:
        docs = list(db["bot_trades"].find().sort("_id", -1).limit(300))
        print("\n(bot_trades window empty — fell back to most-recent 300)")
    t_scores, t_grades, t_style, t_pillar = [], [], defaultdict(list), defaultdict(list)
    for d in docs:
        ec = d.get("entry_context") or {}
        tqs = ec.get("tqs") or {}
        sc = (tqs.get("score") or tqs.get("post_gate_score")
              or tqs.get("pre_gate_score") or d.get("tqs_score") or 0)
        try:
            sc = float(sc or 0)
        except (TypeError, ValueError):
            sc = 0.0
        if sc > 0:
            t_scores.append(sc)
            t_style[d.get("trade_style") or d.get("scan_tier") or "?"].append(sc)
        g = tqs.get("unified_grade") or tqs.get("post_gate_grade") or d.get("tqs_grade")
        if g:
            t_grades.append(g)
        ps = tqs.get("pillar_scores") or {}
        for p in ("setup", "technical", "fundamental", "context", "execution"):
            if isinstance(ps.get(p), (int, float)):
                t_pillar[p].append(ps[p])
    _report("BOT_TRADES (trades taken)", t_scores, t_grades, t_style, t_pillar)

    print("\n" + "=" * 74)
    print("Done. Read-only. Paste this whole output back to recalibrate the bands.")
    print("=" * 74)


if __name__ == "__main__":
    main()
