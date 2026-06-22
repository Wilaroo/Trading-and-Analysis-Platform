#!/usr/bin/env python3
"""
diag_pillar_exit_edge.py — which pillars carry the edge + is the leak in EXITS (READ-ONLY)
==========================================================================================

Step "B" of the plan. On the SANITIZED bot-own recent set (same funnel as
diag_outcomes_sanitized: bot-own, genuine, reliable-R, winsor ±3, last --days),
joined to each trade's live_alerts tqs_breakdown, answer two things:

  SECTION 1 — PER-PILLAR / PER-SUB-SCORE -> realized R
     corr + tercile win% for each of the 5 pillars and each of the 28 sub-scores.
     Tells us WHICH inputs carry the (thin) edge and which are noise/inverse —
     the map for fixing directional logic and prioritising which dark feeds to light.

  SECTION 2 — EXIT EFFICIENCY (MFE/MAE)
     Uses bot_trades.mfe_r (peak favorable R, manage-loop) w/ alert_outcomes.
     mfe_r_floor fallback. Measures how much of the favorable move we KEEP:
       capture = realized_R / mfe_R  (for trades that reached mfe_R >= 0.5)
     Plus: how many trades reached >=1R MFE then closed <0.3R (gave it back).
     Quantifies the "R-capture ~5%" smell — if entries are fine but capture is
     low, EXITS are the dominant P&L leak (a bigger lever than entry scoring).

100% READ-ONLY.

USAGE (DGX, repo root):
    .venv/bin/python diag_pillar_exit_edge.py --days 21
    .venv/bin/python diag_pillar_exit_edge.py --days 14
"""

import os
import sys
import math
import argparse
from datetime import datetime, timezone, timedelta

PILLARS = ["setup", "technical", "fundamental", "context", "execution"]
SUBS = {
    "setup": ["pattern", "win_rate", "expected_value", "tape", "smb"],
    "technical": ["trend", "rsi", "levels", "volatility", "volume"],
    "fundamental": ["catalyst", "short_interest", "float", "institutional", "earnings", "financial"],
    "context": ["regime", "relative_strength", "time", "sector", "vix", "day", "ai_model"],
    "execution": ["history", "tilt", "entry_tendency", "exit_tendency", "streak"],
}
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

def _pct(v, p):
    if not v:
        return None
    s = sorted(v); k = (len(s) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)

def _pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)

def tercile(pairs):
    """pairs: [(score, r, win)]. Returns (lo_win, hi_win, corr) or None."""
    if len(pairs) < 12:
        return None
    pairs = sorted(pairs, key=lambda x: x[0]); n = len(pairs)
    lo, hi = pairs[:n // 3], pairs[2 * n // 3:]
    lw = sum(1 for _, _, w in lo if w) / len(lo) * 100
    hw = sum(1 for _, _, w in hi if w) / len(hi) * 100
    cor = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
    return lw, hw, cor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--winsor", type=float, default=3.0)
    ap.add_argument("--include-adopted", action="store_true")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set."); sys.exit(2)
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=4000)[
        os.environ.get("DB_NAME", "tradecommand")]

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    closed = list(db["bot_trades"].find(
        {"status": {"$in": ["closed", "CLOSED"]}, "closed_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "trade_id": 1, "alert_id": 1, "symbol": 1, "setup_type": 1,
         "direction": 1, "entered_by": 1, "source": 1, "close_reason": 1, "fill_price": 1,
         "exit_price": 1, "stop_price": 1, "stop_loss": 1, "realized_pnl": 1, "shares": 1,
         "tqs_score": 1, "mfe_r": 1, "mae_r": 1}))

    to_map, ao_map = {}, {}
    for d in db["trade_outcomes"].find({}, {"_id": 0, "bot_trade_id": 1, "actual_r": 1, "genuine": 1, "outcome": 1}):
        if d.get("bot_trade_id"):
            to_map[d["bot_trade_id"]] = d
    for d in db["alert_outcomes"].find({}, {"_id": 0, "trade_id": 1, "r_multiple": 1, "genuine": 1,
                                            "outcome": 1, "r_risk_unreliable": 1, "mfe_r_floor": 1, "mae_r_floor": 1}):
        if d.get("trade_id"):
            ao_map[d["trade_id"]] = d

    san = []  # dict per trade: alert_id, r, win, mfe, mae
    drop_a = drop_g = drop_r = 0
    for bt in closed:
        tid = bt.get("id") or bt.get("trade_id")
        if not args.include_adopted and is_adopted(bt.get("entered_by"), bt.get("source"), bt.get("close_reason")):
            drop_a += 1; continue
        to = to_map.get(tid); ao = ao_map.get(tid)
        genuine = bool(to.get("genuine", True)) if to else (bool(ao.get("genuine", True)) if ao else True)
        if not genuine:
            drop_g += 1; continue
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
        mfe = _f(bt.get("mfe_r")) or (_f(ao.get("mfe_r_floor")) if ao else None)
        mae = _f(bt.get("mae_r")) or (_f(ao.get("mae_r_floor")) if ao else None)
        san.append({"aid": bt.get("alert_id"), "r": max(-args.winsor, min(args.winsor, r)),
                    "raw_r": r, "win": win, "mfe": mfe, "mae": mae, "setup": bt.get("setup_type")})

    # join breakdown
    aids = [s["aid"] for s in san if s["aid"]]
    la = {}
    if aids:
        for d in db["live_alerts"].find({"id": {"$in": aids}}, {"_id": 0, "id": 1, "tqs_breakdown": 1}):
            la[d["id"]] = d.get("tqs_breakdown") or {}
    for s in san:
        s["bd"] = la.get(s["aid"]) or {}

    print("=" * 90)
    print(f"  PILLAR/SUB EDGE + EXIT EFFICIENCY  (sanitized bot-own, last {args.days}d, winsor=±{args.winsor})")
    print("=" * 90)
    print(f"  closed:{len(closed)}  dropped[adopted {drop_a}/artifact {drop_g}/badR {drop_r}]  -> sanitized:{len(san)}")
    joined = [s for s in san if s["bd"]]
    print(f"  joined to breakdown: {len(joined)}")

    # ── SECTION 1: per-pillar ────────────────────────────────────────────
    print("\n" + "-" * 90)
    print("  SECTION 1a — PER-PILLAR -> realized R   (corr + tercile win%)")
    print(f"  {'pillar':<14}{'n':>5}{'corr':>8}{'low win%':>10}{'high win%':>11}{'spread':>8}")
    pill_rows = []
    for p in PILLARS:
        pairs = []
        for s in joined:
            sc = _f((s["bd"].get(p) or {}).get("score"))
            if sc is not None:
                pairs.append((sc, s["r"], s["win"]))
        t = tercile(pairs)
        if t:
            lw, hw, cor = t
            pill_rows.append((p, len(pairs), cor, lw, hw, hw - lw))
    for p, n, cor, lw, hw, sp in sorted(pill_rows, key=lambda x: -(x[5])):
        print(f"  {p:<14}{n:>5}{(f'{cor:+.3f}' if cor is not None else 'n/a'):>8}"
              f"{lw:>10.1f}{hw:>11.1f}{sp:>8.1f}")

    # ── per-sub-score ────────────────────────────────────────────────────
    print("\n  SECTION 1b — PER-SUB-SCORE -> realized R   (corr, ranked by |corr|; needs variance)")
    sub_rows = []
    for p in PILLARS:
        for sub in SUBS[p]:
            xs, ys = [], []
            for s in joined:
                sc = _f(((s["bd"].get(p) or {}).get("components") or {}).get(sub))
                if sc is not None:
                    xs.append(sc); ys.append(s["r"])
            if len(xs) >= 15 and (max(xs) - min(xs)) > 1:  # need variance
                cor = _pearson(xs, ys)
                if cor is not None:
                    sub_rows.append((f"{p}.{sub}", len(xs), cor, max(xs) - min(xs)))
    print(f"  {'sub-score':<28}{'n':>5}{'corr':>8}{'range':>8}")
    for name, n, cor, rng in sorted(sub_rows, key=lambda x: -abs(x[2]))[:14]:
        tag = "  <- predictive" if cor > 0.12 else ("  <- INVERSE" if cor < -0.12 else "")
        print(f"  {name:<28}{n:>5}{cor:>+8.3f}{rng:>8.0f}{tag}")

    # ── SECTION 2: exit efficiency ───────────────────────────────────────
    print("\n" + "-" * 90)
    print("  SECTION 2 — EXIT EFFICIENCY (MFE/MAE)")
    haave = [s for s in san if s["mfe"] is not None]
    print(f"  trades with MFE data: {len(haave)}/{len(san)}")
    if haave:
        mfes = [s["mfe"] for s in haave]
        maes = [s["mae"] for s in haave if s["mae"] is not None]
        rs = [s["raw_r"] for s in haave]
        print(f"  avg realized R={sum(rs)/len(rs):+.3f}   avg MFE_R={sum(mfes)/len(mfes):+.3f}"
              f"   avg MAE_R={(sum(maes)/len(maes)) if maes else float('nan'):+.3f}")
        # capture ratio on trades that reached a real favorable move
        movers = [s for s in haave if s["mfe"] and s["mfe"] >= 0.5]
        if movers:
            caps = [max(-2, min(2, s["raw_r"] / s["mfe"])) for s in movers]
            print(f"\n  CAPTURE RATIO (realized_R / MFE_R, for {len(movers)} trades that reached >=0.5R MFE):")
            print(f"     p25={_pct(caps,25):+.2f}  median={_pct(caps,50):+.2f}  p75={_pct(caps,75):+.2f}"
                  f"   mean={sum(caps)/len(caps):+.2f}")
            gaveback = sum(1 for s in movers if s["mfe"] >= 1.0 and s["raw_r"] < 0.3)
            runners = sum(1 for s in movers if s["mfe"] >= 1.0)
            print(f"     reached >=1.0R MFE: {runners}   of those closed <0.3R (gave it back): "
                  f"{gaveback}  ({(gaveback/runners*100) if runners else 0:.0f}%)")
        print("\n  READ: if median capture is low (say <0.4) and many >=1R runners closed <0.3R,")
        print("  the dominant leak is EXITS, not entry scoring — prioritise exit logic. If capture")
        print("  is healthy, the thin edge is an ENTRY/score problem (light feeds / fix signs).")
    print("\n" + "=" * 90)


if __name__ == "__main__":
    main()
