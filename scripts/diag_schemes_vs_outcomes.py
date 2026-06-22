#!/usr/bin/env python3
"""
diag_schemes_vs_outcomes.py — which AGGREGATION best predicts outcomes (READ-ONLY)
==================================================================================

Capstone of the TQS scoring investigation. Earlier we proved (sanitized, bot-own,
recent) that the CURRENT composite (scheme A) is mildly PREDICTIVE (corr ~+0.08..
+0.12, high tercile 52-55% win vs low 37-43%). Now the real question:

   does any aggregation scheme A/B/C/D/E separate winners BETTER than A?

Method:
  1. Build the SANITIZED validation set (same funnel as diag_outcomes_sanitized):
     closed bot_trades, last --days, bot-own, genuine, reliable R, winsorized.
  2. Join each trade to its originating alert's tqs_breakdown via
     bot_trades.alert_id -> live_alerts.id (report join coverage).
  3. Recompute the A-E composites from that breakdown (same math as
     diag_tqs_schemes.py).
  4. For EACH scheme: tercile win%/avgR + corr(scheme_score, realized R).
  5. Rank schemes by discrimination (high-low win% spread, then corr).

The winner is the scheme whose high-score bucket wins the most — NOT the one that
spreads the most. 100% READ-ONLY.

USAGE (DGX, repo root):
    .venv/bin/python diag_schemes_vs_outcomes.py --days 14
    .venv/bin/python diag_schemes_vs_outcomes.py --days 21 --gain 8
    .venv/bin/python diag_schemes_vs_outcomes.py --selftest
"""

import os
import sys
import math
import argparse
from datetime import datetime, timezone, timedelta

# ── scheme math (mirrors diag_tqs_schemes.py, sub-weights == live *_quality.py) ─
SUB_WEIGHTS = {
    "setup":       {"pattern": .20, "win_rate": .15, "expected_value": .30, "tape": .20, "smb": .15},
    "technical":   {"trend": .25, "rsi": .20, "levels": .20, "volatility": .15, "volume": .20},
    "fundamental": {"catalyst": .25, "short_interest": .20, "float": .15, "institutional": .10, "earnings": .10, "financial": .20},
    "context":     {"regime": .22, "relative_strength": .20, "time": .18, "sector": .15, "vix": .12, "ai_model": .10, "day": .03},
    "execution":   {"history": .25, "tilt": .30, "entry_tendency": .15, "exit_tendency": .15, "streak": .15},
}
PILLARS = list(SUB_WEIGHTS.keys())
DEFAULT_PW = {"setup": .20, "technical": .25, "fundamental": .15, "context": .20, "execution": .20}

def _approx(a, b, t=1e-6):
    try:
        return abs(float(a) - float(b)) <= t
    except (TypeError, ValueError):
        return False

DEFAULT_DETECTORS = {
    ("setup", "win_rate"): lambda r: _approx(r.get("win_rate"), 0.5),
    ("technical", "trend"): lambda r: str(r.get("ma_stack")) == "neutral",
    ("technical", "rsi"): lambda r: _approx(r.get("rsi"), 50.0),
    ("technical", "volatility"): lambda r: _approx(r.get("atr_percent"), 2.0),
    ("technical", "volume"): lambda r: _approx(r.get("rvol"), 1.0),
    ("context", "vix"): lambda r: _approx(r.get("vix_level"), 18.0),
    ("execution", "exit_tendency"): lambda r: _approx(r.get("avg_r_capture_pct"), 75.0),
}
PROXY_HINTS = ("est.", "proxy", "no live")
ABSENT_HINTS = ("no data", "no tape", "no clear catalyst", "no short-interest", "no float",
                "no institutional", "no relative-strength", "no model signal", "no entry-execution",
                "no ib financials", "sector data unavailable", "limited execution history", "no earnings within")

def classify(pillar, sub, disp_block, raw):
    verdict = ((disp_block or {}).get("verdict", "") or "").strip().lower()
    reading = ((disp_block or {}).get("reading", "") or "").lower()
    if verdict == "no data":
        return "absent"
    if any(h in reading for h in PROXY_HINTS):
        return "proxy"
    if any(h in reading for h in ABSENT_HINTS):
        return "absent"
    det = DEFAULT_DETECTORS.get((pillar, sub))
    if det:
        try:
            if det(raw or {}):
                return "default"
        except Exception:
            pass
    return "ok"

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def pillar_schemes(pillar, comps, disp, raw, gain):
    w = SUB_WEIGHTS[pillar]
    A = 0.0; Cs = 0.0; Bp = Bw = 0.0; Dp = Dw = 0.0
    for sub, wi in w.items():
        if sub not in comps:
            continue
        try:
            c = float(comps[sub])
        except (TypeError, ValueError):
            continue
        kind = classify(pillar, sub, disp.get(sub), raw)
        A += wi * c
        if kind in ("ok", "proxy"):
            s = _clamp((c - 50.0) / 5.0, -10, 10)
            Cs += wi * s; Bp += wi * c; Bw += wi; Dp += wi * s; Dw += wi
    B = (Bp / Bw) if Bw > 0 else 50.0
    C = _clamp(50.0 + 5.0 * Cs, 0, 100)
    D = _clamp(50.0 + gain * ((Dp / Dw) if Dw > 0 else 0.0), 0, 100)
    return {"A": A, "B": B, "C": C, "D": D}

def composite_E(bd, comp_B):
    caps = []; bonus = 0.0
    def g(p, s):
        try:
            return float((bd.get(p, {}).get("components", {}) or {}).get(s))
        except (TypeError, ValueError):
            return None
    for (p, s, thr, cap) in [("technical", "trend", 25, 60), ("technical", "rsi", 25, 62),
                             ("execution", "tilt", 20, 50), ("execution", "streak", 25, 65)]:
        v = g(p, s)
        if v is not None and v <= thr:
            caps.append(cap)
    for (p, s, thr, bn) in [("setup", "tape", 80, 3), ("context", "relative_strength", 85, 3),
                            ("context", "sector", 90, 2)]:
        v = g(p, s)
        if v is not None and v >= thr:
            bonus += bn
    val = comp_B + bonus
    if caps:
        val = min(val, min(caps))
    return _clamp(val, 0, 100)

def score_breakdown(bd, pw, gain):
    tw = sum(pw.get(p, 0) for p in PILLARS) or 1.0
    pw = {p: pw.get(p, 0) / tw for p in PILLARS}
    po = {}
    for p in PILLARS:
        pdct = bd.get(p) or {}
        po[p] = pillar_schemes(p, pdct.get("components") or {}, pdct.get("display") or {},
                               pdct.get("raw_values") or {}, gain)
    comp = {k: sum(pw[p] * po[p][k] for p in PILLARS) for k in ("A", "B", "C", "D")}
    comp["E"] = composite_E(bd, comp["B"])
    return comp

# ── sanitize funnel helpers (mirror diag_outcomes_sanitized.py) ───────────────
_ADOPTED_HINTS = ("reconcil", "external", "excess", "adopt", "orphan", "ib_only", "ib-only", "imported")

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def _dir(d):
    return str(getattr(d, "value", d) or "long").lower()

def is_adopted(eb="", src="", cr=""):
    return any(h in f"{eb or ''} {src or ''} {cr or ''}".lower() for h in _ADOPTED_HINTS)

def realized_r(bt):
    entry = _f(bt.get("fill_price")); direction = _dir(bt.get("direction"))
    stop = _f(bt.get("stop_price")) or _f(bt.get("stop_loss")); xp = _f(bt.get("exit_price"))
    if not xp:
        realized = _f(bt.get("realized_pnl")); sh = _f(bt.get("shares"))
        if entry and realized is not None and sh and sh > 0:
            pps = realized / sh
            xp = entry + pps if direction == "long" else entry - pps
    if not (entry and xp and stop):
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return ((xp - entry) if direction == "long" else (entry - xp)) / risk

def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)

def tercile_stats(rows, key_idx):
    """rows: list of (scoredict, r, win). Returns (lo_win, hi_win, spread, corr, n)."""
    pts = [(rd[key_idx], r, w) for rd, r, w in rows]
    pts.sort(key=lambda x: x[0])
    n = len(pts)
    if n < 12:
        return None
    lo = pts[:n // 3]; hi = pts[2 * n // 3:]
    lo_win = sum(1 for _, _, w in lo if w) / len(lo) * 100
    hi_win = sum(1 for _, _, w in hi if w) / len(hi) * 100
    lo_r = sum(r for _, r, _ in lo) / len(lo)
    hi_r = sum(r for _, r, _ in hi) / len(hi)
    cor = _pearson([p[0] for p in pts], [p[1] for p in pts])
    return dict(lo_win=lo_win, hi_win=hi_win, spread=hi_win - lo_win,
                lo_r=lo_r, hi_r=hi_r, dr=hi_r - lo_r, corr=cor, n=n)


def main():
    ap = argparse.ArgumentParser(description="which aggregation best predicts outcomes")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--winsor", type=float, default=3.0)
    ap.add_argument("--gain", type=float, default=8.0)
    ap.add_argument("--include-adopted", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        bd = {p: {"components": {s: 70 for s in SUB_WEIGHTS[p]},
                  "display": {s: {"verdict": "Favorable", "reading": "x"} for s in SUB_WEIGHTS[p]},
                  "raw_values": {}} for p in PILLARS}
        c = score_breakdown(bd, DEFAULT_PW, 5.0)
        assert _approx(c["A"], 70) and _approx(c["B"], 70) and _approx(c["C"], 70), c
        print(f"selftest OK: all-70 breakdown -> {c}")
        return

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set."); sys.exit(2)
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=4000)[
        os.environ.get("DB_NAME", "tradecommand")]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    closed = list(db["bot_trades"].find(
        {"status": {"$in": ["closed", "CLOSED"]}, "closed_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "trade_id": 1, "alert_id": 1, "direction": 1,
         "entered_by": 1, "source": 1, "close_reason": 1, "fill_price": 1,
         "exit_price": 1, "stop_price": 1, "stop_loss": 1, "realized_pnl": 1,
         "shares": 1, "tqs_score": 1}))

    to_map, ao_map = {}, {}
    for d in db["trade_outcomes"].find({}, {"_id": 0, "bot_trade_id": 1, "actual_r": 1, "genuine": 1, "outcome": 1}):
        if d.get("bot_trade_id"):
            to_map[d["bot_trade_id"]] = d
    for d in db["alert_outcomes"].find({}, {"_id": 0, "trade_id": 1, "r_multiple": 1, "genuine": 1, "outcome": 1, "r_risk_unreliable": 1}):
        if d.get("trade_id"):
            ao_map[d["trade_id"]] = d

    # sanitized set with realized R + alert_id
    san = []  # (alert_id, r, win, tqs_score)
    drop_adopted = drop_art = drop_r = 0
    for bt in closed:
        tid = bt.get("id") or bt.get("trade_id")
        if not args.include_adopted and is_adopted(bt.get("entered_by"), bt.get("source"), bt.get("close_reason")):
            drop_adopted += 1; continue
        to = to_map.get(tid); ao = ao_map.get(tid)
        genuine = bool(to.get("genuine", True)) if to else (bool(ao.get("genuine", True)) if ao else True)
        if not genuine:
            drop_art += 1; continue
        if ao and ao.get("r_risk_unreliable"):
            drop_r += 1; continue
        r = None; outcome = None
        if to and to.get("actual_r") is not None:
            r = _f(to.get("actual_r")); outcome = to.get("outcome")
        elif ao and ao.get("r_multiple") is not None:
            r = _f(ao.get("r_multiple")); outcome = ao.get("outcome")
        else:
            r = realized_r(bt)
        if r is None:
            drop_r += 1; continue
        win = (outcome == "won") if outcome in ("won", "lost", "scratch") else (r > 0)
        r = max(-args.winsor, min(args.winsor, r))
        san.append((bt.get("alert_id"), r, win, _f(bt.get("tqs_score"))))

    # join breakdowns via live_alerts.id
    aids = [a for a, _, _, _ in san if a]
    la_map = {}
    if aids:
        for d in db["live_alerts"].find({"id": {"$in": aids}},
                                        {"_id": 0, "id": 1, "tqs_breakdown": 1, "tqs_weights": 1}):
            la_map[d["id"]] = d

    print("=" * 92)
    print(f"  SCHEME vs OUTCOME  (sanitized bot-own{' +adopted' if args.include_adopted else ''}, "
          f"last {args.days}d, winsor=±{args.winsor}, D-gain={args.gain})")
    print("=" * 92)
    print(f"  closed:{len(closed)}  dropped[adopted {drop_adopted} / artifact {drop_art} / badR {drop_r}]"
          f"  -> sanitized w/ R: {len(san)}")

    rows = []  # (scoredict{A..E}, r, win)
    joined = 0
    for aid, r, win, ts in san:
        la = la_map.get(aid)
        if not la or not la.get("tqs_breakdown"):
            continue
        joined += 1
        pw = la.get("tqs_weights") or DEFAULT_PW
        sc = score_breakdown(la["tqs_breakdown"], pw, args.gain)
        rows.append((sc, r, win))
    print(f"  joined to live_alerts breakdown: {joined}/{len(san)} "
          f"({(joined/len(san)*100) if san else 0:.0f}% coverage)")

    if joined < 12:
        print("\n  Too few joined breakdowns to rank schemes. The recent originating alerts")
        print("  may have rolled out of live_alerts. Options: shorten the gap (run sooner after")
        print("  closes), widen --days, or fix the tqs_breakdown-on-bot_trades persistence gap so")
        print("  closed trades self-carry the breakdown. (Scheme-A signal already shown via")
        print("  diag_outcomes_sanitized.)")
        print("\n" + "=" * 92)
        return

    keymap = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    # adapt rows to (tuple-of-scores, r, win) for tercile_stats indexing
    arows = [((rd["A"], rd["B"], rd["C"], rd["D"], rd["E"]), r, w) for rd, r, w in rows]
    labels = {"A": "A current weighted avg", "B": "B present-only renorm",
              "C": "C signed absent=0", "D": f"D signed+gain{args.gain}", "E": "E renorm+veto"}
    print(f"\n  n={joined}   ranking by high-low tercile WIN% spread (then corr)\n")
    print(f"  {'scheme':<26}{'corr':>7}{'low win%':>10}{'high win%':>11}{'spread':>8}"
          f"{'low R':>8}{'high R':>8}")
    results = []
    for k, idx in keymap.items():
        st = tercile_stats(arows, idx)
        if not st:
            continue
        results.append((k, st))
    results.sort(key=lambda x: (-(x[1]["spread"]), -(x[1]["corr"] or -9)))
    for k, st in results:
        cor = st["corr"]
        print(f"  {labels[k]:<26}{(f'{cor:+.3f}' if cor is not None else '   n/a'):>7}"
              f"{st['lo_win']:>10.1f}{st['hi_win']:>11.1f}{st['spread']:>8.1f}"
              f"{st['lo_r']:>+8.3f}{st['hi_r']:>+8.3f}")
    best = results[0][0]
    print(f"\n  BEST separator: scheme {best} "
          f"(win% spread {results[0][1]['spread']:.1f}, corr {results[0][1]['corr']:+.3f})")
    print("  READ: a scheme that lifts high-tercile win% / corr meaningfully above A means the")
    print("  AGGREGATION matters -> adopt it. If all ~tie with A, aggregation is a wash and the")
    print("  lever is the INPUTS (light dark feeds / fix degenerate sub-scores). n is small —")
    print("  treat as directional; re-run as clean bot-own sample grows.")
    print("\n" + "=" * 92)


if __name__ == "__main__":
    main()
