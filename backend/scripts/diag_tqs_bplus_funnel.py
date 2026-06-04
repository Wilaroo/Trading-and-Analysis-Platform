#!/usr/bin/env python3
"""
diag_tqs_bplus_funnel.py  (READ-ONLY)
=====================================
Answers, in one run, the three questions:

  Q1  Has the bot FOUND any B-or-above (TQS) setups recently?
  Q2  Has it TAKEN any of those trades?
  Q3  WHY isn't it finding / taking more B-or-above setups?

It separates the two failure modes:

  • SUPPLY problem  — few alerts ever reach a B grade because the 5-pillar
    composite is compressed into a narrow band (and/or one pillar caps it).
    Diagnosed via the score distribution, per-pillar medians, and the
    calibration floors.

  • CONVERSION problem — B+ alerts ARE found but never become trades.
    Diagnosed via the GRADE×ACTION cross-tab (the calibrated grade says
    "B" but the ABSOLUTE action threshold BUY>=65 says "HOLD"), the
    taken-vs-found join, and the trade_drops killing-gate tally.

Reads Mongo only (MONGO_URL / DB_NAME from backend/.env). Writes nothing.

Run from repo root on the DGX:
    .venv/bin/python backend/scripts/diag_tqs_bplus_funnel.py --days 7
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Absolute action thresholds the engine uses (tqs_engine.ACTION_THRESHOLDS).
ACT_STRONG_BUY, ACT_BUY, ACT_HOLD, ACT_AVOID = 80, 65, 50, 35
# Calibration absolute FLOORS (grade_calibration._floors defaults; env-tunable).
B_FLOOR = float(os.environ.get("TQS_CAL_FLOOR_B", "57"))
A_FLOOR = float(os.environ.get("TQS_CAL_FLOOR_A", "60"))
PCT_A = float(os.environ.get("TQS_CAL_PCT_A", "90"))
PCT_B = float(os.environ.get("TQS_CAL_PCT_B", "70"))
PILLARS = ["setup", "technical", "fundamental", "context", "execution"]


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
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not url or not name:
        print("ERROR: MONGO_URL / DB_NAME not set.")
        sys.exit(1)
    return MongoClient(url, serverSelectionTimeoutMS=4000)[name]


def _to_dt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _pcts(vals):
    if not vals:
        return {}
    s = sorted(vals)
    n = len(s)

    def p(q):
        return s[min(n - 1, max(0, int(q * n)))]
    return {
        "n": n, "min": round(s[0], 1), "p10": round(p(0.10), 1),
        "p25": round(p(0.25), 1), "p50": round(p(0.50), 1),
        "p75": round(p(0.75), 1), "p90": round(p(0.90), 1),
        "max": round(s[-1], 1), "mean": round(statistics.mean(s), 1),
        "stdev": round(statistics.pstdev(s), 2) if n > 1 else 0.0,
    }


def _gbucket(grade):
    """Collapse any grade label to its first letter (A/B/C/D/F/?)."""
    if not grade or not isinstance(grade, str) or not grade.strip():
        return "?"
    return grade.strip()[0].upper()


def _is_bplus(grade):
    return _gbucket(grade) in ("A", "B")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    _load_env()
    db = _db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    print(f"\n{'#'*92}\n#  TQS B+ SUPPLY / CONVERSION DIAGNOSTIC   window={args.days}d "
          f"(since {cutoff_str})\n{'#'*92}")

    # ── load alerts in window ───────────────────────────────────────────
    alerts = list(db["live_alerts"].find(
        {"created_at": {"$gte": cutoff_str}},
        {"_id": 0, "id": 1, "symbol": 1, "setup_type": 1, "direction": 1,
         "created_at": 1, "time_window": 1, "tqs_score": 1, "tqs_grade": 1,
         "tqs_action": 1, "tqs_pillar_scores": 1},
    ))
    # Some deployments store created_at as a datetime; re-filter defensively.
    alerts = [a for a in alerts
              if (_to_dt(a.get("created_at")) or cutoff) >= cutoff or True]
    scored = [a for a in alerts if float(a.get("tqs_score") or 0) > 0]
    rth = [a for a in scored if a.get("time_window") not in ("premarket", "closed")]

    print(f"\n[1] SUPPLY — alerts scanner produced")
    print(f"    total alerts in window      : {len(alerts)}")
    print(f"    TQS-scored (tqs_score>0)    : {len(scored)}")
    print(f"    RTH-pure scored             : {len(rth)}")
    if not scored:
        print("\n    No TQS-scored alerts in window — scanner may be off, or no "
              "RTH sessions in range. Stop here.")
        return

    base = rth if rth else scored
    label = "RTH-pure" if rth else "all-session"
    scores = [float(a["tqs_score"]) for a in base]
    st = _pcts(scores)
    print(f"\n    RAW tqs_score distribution ({label}, n={st['n']}):")
    print(f"      min={st['min']}  p10={st['p10']}  p25={st['p25']}  med={st['p50']}  "
          f"p75={st['p75']}  p90={st['p90']}  max={st['max']}  mean={st['mean']}  stdev={st['stdev']}")

    def pct_over(thr):
        return 100.0 * sum(1 for s in scores if s >= thr) / len(scores)
    print(f"\n    % of scored alerts clearing each ABSOLUTE bar:")
    print(f"      >= {B_FLOOR:.0f} (B grade floor) : {pct_over(B_FLOOR):5.1f}%")
    print(f"      >= {A_FLOOR:.0f} (A grade floor) : {pct_over(A_FLOOR):5.1f}%")
    print(f"      >= {ACT_BUY} (action=BUY)     : {pct_over(ACT_BUY):5.1f}%   <-- gate to actually trade")
    print(f"      >= {ACT_STRONG_BUY} (STRONG_BUY)    : {pct_over(ACT_STRONG_BUY):5.1f}%")

    # grade + action distribution
    gdist = Counter(_gbucket(a.get("tqs_grade")) for a in base)
    adist = Counter((a.get("tqs_action") or "?") for a in base)
    print(f"\n    Calibrated GRADE distribution: " +
          "  ".join(f"{g}={gdist.get(g,0)}" for g in ("A", "B", "C", "D", "F", "?")))
    print(f"    ACTION distribution          : " +
          "  ".join(f"{k}={v}" for k, v in adist.most_common()))

    bplus = [a for a in base if _is_bplus(a.get("tqs_grade"))]
    print(f"\n    >>> Q1 ANSWER: B-or-above GRADED alerts in {args.days}d = {len(bplus)} "
          f"({100.0*len(bplus)/len(base):.1f}% of scored)")

    # ── 2. the GRADE x ACTION disconnect ────────────────────────────────
    print(f"\n[2] GRADE x ACTION cross-tab — the 'graded B but not actionable' test")
    print(f"    (grade is percentile-calibrated; action uses ABSOLUTE score>= {ACT_BUY})")
    xt = defaultdict(Counter)
    for a in base:
        xt[_gbucket(a.get("tqs_grade"))][a.get("tqs_action") or "?"] += 1
    hdr = ["STRONG_BUY", "BUY", "HOLD", "AVOID", "STRONG_AVOID", "?"]
    print(f"      {'grade':<6}" + "".join(f"{h:>13}" for h in hdr))
    for g in ("A", "B", "C", "D", "F"):
        if sum(xt[g].values()) == 0:
            continue
        print(f"      {g:<6}" + "".join(f"{xt[g].get(h,0):>13}" for h in hdr))
    bplus_actionable = sum(1 for a in bplus if (a.get("tqs_action") in ("BUY", "STRONG_BUY")))
    if bplus:
        print(f"\n    >>> Of {len(bplus)} B+ graded alerts, only {bplus_actionable} "
              f"({100.0*bplus_actionable/len(bplus):.1f}%) carry a BUY/STRONG_BUY action.")
        if bplus_actionable < 0.5 * len(bplus):
            print("        ⚠ DISCONNECT: percentile grade says B+ but absolute action "
                  "says HOLD. The action threshold was NOT recalibrated with the grade.")

    # ── 3. pillar decomposition ─────────────────────────────────────────
    print(f"\n[3] PILLAR decomposition — which pillar caps the composite?")
    print(f"      {'pillar':<12}{'med':>7}{'p10':>7}{'p90':>7}{'stdev':>8}")
    pill_meds = {}
    for p in PILLARS:
        vals = [float((a.get("tqs_pillar_scores") or {}).get(p))
                for a in base if (a.get("tqs_pillar_scores") or {}).get(p) is not None]
        if not vals:
            print(f"      {p:<12}{'(no data)':>7}")
            continue
        pc = _pcts(vals)
        pill_meds[p] = pc["p50"]
        print(f"      {p:<12}{pc['p50']:>7}{pc['p10']:>7}{pc['p90']:>7}{pc['stdev']:>8}")
    if pill_meds:
        worst = min(pill_meds, key=pill_meds.get)
        print(f"\n    >>> Lowest-median pillar: '{worst}' (med={pill_meds[worst]}) "
              f"— prime candidate dragging the composite below the B floor.")

    # ── 4. calibration reference state ──────────────────────────────────
    print(f"\n[4] CALIBRATION state (percentile cuts A>= {PCT_A:.0f}pct / B>= {PCT_B:.0f}pct, "
          f"floors A>= {A_FLOOR:.0f} / B>= {B_FLOOR:.0f})")
    print(f"    A grade needs BOTH top-{100-PCT_A:.0f}% rank AND raw>= {A_FLOOR:.0f}.")
    print(f"    B grade needs BOTH top-{100-PCT_B:.0f}% rank AND raw>= {B_FLOOR:.0f}.")
    if st["p90"] < B_FLOOR:
        print(f"    ⚠ p90 raw score ({st['p90']}) is BELOW the B floor ({B_FLOOR:.0f}) "
              f"→ the floor alone blocks ~all B grades regardless of rank.")
    elif st["p75"] < B_FLOOR:
        print(f"    ⚠ p75 raw score ({st['p75']}) < B floor ({B_FLOOR:.0f}) — only the very "
              f"top of the distribution can clear it.")

    # ── 5. taken trades ─────────────────────────────────────────────────
    print(f"\n[5] TAKEN — what the bot actually traded ({args.days}d)")
    trades = list(db["bot_trades"].find(
        {"created_at": {"$gte": cutoff_str}},
        {"_id": 0, "alert_id": 1, "symbol": 1, "setup_type": 1, "created_at": 1,
         "tqs_score": 1, "tqs_grade": 1, "tqs_action": 1, "entry_context": 1,
         "entered_by": 1},
    ))
    # also tolerate datetime created_at
    if not trades:
        trades = list(db["bot_trades"].find(
            {"created_at": {"$gte": cutoff}},
            {"_id": 0, "alert_id": 1, "symbol": 1, "setup_type": 1, "created_at": 1,
             "tqs_score": 1, "tqs_grade": 1, "tqs_action": 1, "entry_context": 1,
             "entered_by": 1}))

    def trade_grade(t):
        g = t.get("tqs_grade")
        if not g:
            g = ((t.get("entry_context") or {}).get("tqs") or {}).get("grade")
        return g
    tg = Counter(_gbucket(trade_grade(t)) for t in trades)
    bplus_taken = [t for t in trades if _is_bplus(trade_grade(t))]
    print(f"    total trades                : {len(trades)}")
    print(f"    grade distribution          : " +
          "  ".join(f"{g}={tg.get(g,0)}" for g in ("A", "B", "C", "D", "F", "?")))
    print(f"\n    >>> Q2 ANSWER: B-or-above trades TAKEN = {len(bplus_taken)}")

    # ── 6. conversion / funnel for B+ alerts ────────────────────────────
    print(f"\n[6] CONVERSION — of the {len(bplus)} B+ alerts found, how many became trades?")
    taken_alert_ids = {t.get("alert_id") for t in trades if t.get("alert_id")}
    taken_symsetup = {(t.get("symbol"), t.get("setup_type")) for t in trades}
    matched, unmatched = [], []
    for a in bplus:
        if a.get("id") in taken_alert_ids or (a.get("symbol"), a.get("setup_type")) in taken_symsetup:
            matched.append(a)
        else:
            unmatched.append(a)
    print(f"    B+ alerts converted to a trade : {len(matched)}")
    print(f"    B+ alerts NOT taken            : {len(unmatched)}")
    if bplus:
        print(f"    conversion rate                : {100.0*len(matched)/len(bplus):.1f}%")

    # drops for the untaken B+ symbols
    if unmatched:
        unsyms = {a.get("symbol") for a in unmatched}
        drops = list(db["trade_drops"].find(
            {"symbol": {"$in": list(unsyms)}},
            {"_id": 0, "gate": 1, "symbol": 1, "setup_type": 1, "reason": 1, "ts": 1}))
        gate_ct = Counter(d.get("gate") for d in drops)
        print(f"\n    trade_drops gates for untaken-B+ symbols (last 7d TTL):")
        if gate_ct:
            for g, c in gate_ct.most_common(10):
                print(f"      {c:>4}  {g}")
        else:
            print("      (no trade_drops rows — they may have aged out, or the B+ alerts "
                  "never reached the execution funnel at all, i.e. HOLD action upstream)")

    # ── 7. setups currently F-gated (whole families blocked) ────────────
    print(f"\n[7] SETUP-GRADE F-GATE — setup families blocked by v173 (avg_r<0, n>=5)")
    f_setups = []
    for ss in db["strategy_stats"].find(
            {}, {"_id": 0, "strategy": 1, "setup_type": 1, "avg_r": 1,
                 "sample_size": 1, "total_trades": 1, "win_rate": 1}):
        n = ss.get("sample_size") or ss.get("total_trades") or 0
        avg_r = ss.get("avg_r")
        if n >= 5 and isinstance(avg_r, (int, float)) and avg_r < 0:
            f_setups.append((ss.get("strategy") or ss.get("setup_type"),
                             round(avg_r, 2), n, ss.get("win_rate")))
    if f_setups:
        print(f"    {len(f_setups)} setup(s) graded F → blocked (or 0.1x micro):")
        for name, avg_r, n, wr in sorted(f_setups, key=lambda x: x[1]):
            print(f"      {name:<28} avg_r={avg_r:>6}  n={n:>4}  win_rate={wr}")
    else:
        print("    none — no setup family is currently F-blocked.")

    # ── 8. verdict ──────────────────────────────────────────────────────
    print(f"\n{'='*92}\nVERDICT\n{'='*92}")
    supply_problem = (len(bplus) < 0.15 * len(base)) or (st["p90"] < B_FLOOR)
    conversion_problem = bool(bplus) and (len(matched) < 0.25 * len(bplus))
    action_disconnect = bool(bplus) and (bplus_actionable < 0.5 * len(bplus))
    if supply_problem:
        print(f"• SUPPLY: only {len(bplus)}/{len(base)} alerts reach B+ and the score "
              f"distribution is compressed (p90={st['p90']} vs B-floor {B_FLOOR:.0f}). "
              f"Lowest pillar = '{min(pill_meds, key=pill_meds.get) if pill_meds else '?'}'. "
              f"Fix at the SCORING layer (de-compress the capping pillar and/or lower the "
              f"B floor / recalibrate cuts).")
    if action_disconnect:
        print(f"• ACTION DISCONNECT: B+ grade ≠ BUY action ({bplus_actionable}/{len(bplus)} "
              f"actionable). The percentile grade and the absolute action threshold "
              f"(BUY>= {ACT_BUY}) are on different scales. Recalibrate ACTION_THRESHOLDS to "
              f"the live distribution OR drive execution off the calibrated grade.")
    if conversion_problem and not action_disconnect:
        print(f"• CONVERSION: B+ found but only {len(matched)}/{len(bplus)} taken — inspect "
              f"the trade_drops gates above + the AI confidence gate.")
    if not (supply_problem or conversion_problem or action_disconnect):
        print("• Healthy: B+ supply and conversion both look reasonable in this window.")
    print(f"\nDone (read-only).")


if __name__ == "__main__":
    main()
