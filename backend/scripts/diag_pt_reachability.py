#!/usr/bin/env python3
"""
diag_pt_reachability.py — READ-ONLY probe: why ZERO target_hit closes?
=======================================================================
Runs on the SANITIZED CORE ids written by diag_sanitized_closed_trades.py
(sanitize_v2, /tmp/sanitized_trade_ids.json). Measures, per clean trade:

  * bracket GEOMETRY — stop distance as % of entry and in DAILY-ATR units
    (entry_context.atr), and the first/last profit targets in R and ATR.
    Hypothesis: intraday stops are sized off the DAILY ATR (1.3-2.0x),
    then PTs are laddered at 1.5R/2.5R on top => PT sits 2-5 DAILY ATRs
    away on a trade that only lives a few hours. (OXY 06-12: entry 55.52,
    SL 57.92 = 1.3x daily ATR, PT 49.94 = 3.1x daily ATR intraday.)
  * MFE REACH — how far price actually ran in our favor (R units), with
    fallback reconstruction when the manage loop never stamped mfe.
  * PT REACHABILITY — % of trades whose MFE actually touched PT1; trades
    that TOUCHED PT1 but closed for another reason = execution gap.
  * CLOCK COST — for eod/decay closes: peak MFE vs realized R ("was +0.8R
    at peak, clock closed it at -0.1R").
  * COUNTERFACTUAL PT SWEEP — avgR/hit-rate if PT1 were at 0.5/0.75/1.0/
    1.25/1.5/2.0R (exit at +X when mfe_r >= X else realized R). Valid
    path-wise because MFE always occurs BEFORE the close; caveat: ignores
    scale-out partials.

No writes. Run after diag_sanitized_closed_trades.py on the same day:
  .venv/bin/python /tmp/diag_pt_reachability.py
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

IDS_PATH = "/tmp/sanitized_trade_ids.json"
CF_RUNGS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]


def _load_env():
    for cand in (Path.cwd() / "backend" / ".env",
                 Path(__file__).resolve().parents[1] / ".env"):
        if cand.exists():
            for line in cand.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r_multiple(t):
    pnl = t.get("net_pnl")
    if pnl in (None, 0):
        pnl = t.get("realized_pnl") if t.get("realized_pnl") not in (None, 0) else t.get("pnl")
    risk = _f(t.get("risk_amount"))
    pnl = _f(pnl)
    if pnl is None or not risk:
        return None
    return pnl / risk


def _pcts(vals, ps=(25, 50, 75)):
    if not vals:
        return "n=0"
    s = sorted(vals)
    n = len(s)
    out = []
    for p in ps:
        out.append(f"p{p}={s[min(n - 1, int(n * p / 100))]:.2f}")
    return f"n={n} " + " ".join(out)


def _analyze(t):
    """Returns per-trade geometry dict or None if unusable."""
    entry = _f(t.get("fill_price")) or _f(t.get("entry_price"))
    stop = _f(t.get("stop_price"))
    if not entry or entry <= 0 or not stop or stop <= 0:
        return None
    d = str(t.get("direction") or "long").lower()
    sign = 1.0 if d != "short" else -1.0
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return None
    tps = t.get("target_prices") or []
    if isinstance(tps, (int, float)):
        tps = [tps]
    tps = [x for x in (_f(p) for p in tps) if x and x > 0]
    pt_dists = sorted(abs(p - entry) for p in tps) if tps else []
    pt1 = pt_dists[0] if pt_dists else None
    ptL = pt_dists[-1] if pt_dists else None

    atr = _f((t.get("entry_context") or {}).get("atr"))

    # MFE move (absolute $ in our favor), best-available source:
    mfe_move = None
    mfe_price = _f(t.get("mfe_price"))
    if mfe_price and mfe_price > 0:
        mfe_move = (mfe_price - entry) * sign
    if mfe_move is None or mfe_move == 0:
        mr = _f(t.get("mfe_r"))
        if mr and mr > 0:
            mfe_move = mr * stop_dist
    if mfe_move is None or mfe_move == 0:
        # excursion floor: the favorable part the close itself realized
        xp = _f(t.get("exit_price"))
        if xp and xp > 0:
            mfe_move = max(0.0, (xp - entry) * sign)
    mfe_move = max(0.0, mfe_move or 0.0)

    rr = _r_multiple(t)
    return {
        "symbol": t.get("symbol"),
        "style": str(t.get("trade_style") or "?").lower(),
        "setup": str(t.get("setup_type") or "?"),
        "close_reason": str(t.get("close_reason") or "?"),
        "entry": entry,
        "stop_pct": 100.0 * stop_dist / entry,
        "stop_atr": (stop_dist / atr) if atr and atr > 0 else None,
        "pt1_r": (pt1 / stop_dist) if pt1 else None,
        "ptL_r": (ptL / stop_dist) if ptL else None,
        "pt1_atr": (pt1 / atr) if (pt1 and atr and atr > 0) else None,
        "ptL_atr": (ptL / atr) if (ptL and atr and atr > 0) else None,
        "mfe_r": mfe_move / stop_dist,
        "pt1_progress": (mfe_move / pt1) if pt1 else None,
        "realized_r": rr,
        "hold_s": _f(t.get("hold_seconds")),
    }


def main():
    _load_env()
    ids_file = Path(IDS_PATH)
    if not ids_file.exists():
        print(f"ERROR: {IDS_PATH} not found — run diag_sanitized_closed_trades.py first.")
        sys.exit(1)
    payload = json.loads(ids_file.read_text())
    core_ids = payload.get("core_ids") or []
    print("=" * 78)
    print(f"PT-REACHABILITY PROBE — {len(core_ids)} sanitized ids "
          f"({payload.get('filter_version')}, generated {str(payload.get('generated_at'))[:19]})")
    print("=" * 78)

    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "tradecommand")]
    rows = list(db["bot_trades"].find(
        {"id": {"$in": core_ids}},
        {"_id": 0, "id": 1, "symbol": 1, "direction": 1, "trade_style": 1,
         "setup_type": 1, "fill_price": 1, "entry_price": 1, "stop_price": 1,
         "target_prices": 1, "exit_price": 1, "mfe_price": 1, "mfe_r": 1,
         "mae_r": 1, "close_reason": 1, "hold_seconds": 1, "risk_amount": 1,
         "net_pnl": 1, "realized_pnl": 1, "pnl": 1, "shares": 1,
         "entry_context.atr": 1, "entry_context.atr_percent": 1}))

    geos = [g for g in (_analyze(t) for t in rows) if g]
    print(f"usable geometry rows: {len(geos)} of {len(rows)} fetched\n")

    # ── [1] bracket geometry by trade_style ──────────────────────────
    print("[1] BRACKET GEOMETRY BY TRADE STYLE (the 'how wide' question):")
    by_style = defaultdict(list)
    for g in geos:
        by_style[g["style"]].append(g)
    for style in sorted(by_style, key=lambda s: -len(by_style[s])):
        gs = by_style[style]
        print(f"   {style} (n={len(gs)}):")
        print(f"     stop  %entry : {_pcts([g['stop_pct'] for g in gs])}")
        sa = [g["stop_atr"] for g in gs if g["stop_atr"] is not None]
        print(f"     stop  in ATR : {_pcts(sa)}")
        print(f"     PT1   in R   : {_pcts([g['pt1_r'] for g in gs if g['pt1_r']])}")
        print(f"     PTlast in R  : {_pcts([g['ptL_r'] for g in gs if g['ptL_r']])}")
        pa = [g["pt1_atr"] for g in gs if g["pt1_atr"] is not None]
        pl = [g["ptL_atr"] for g in gs if g["ptL_atr"] is not None]
        print(f"     PT1   in ATR : {_pcts(pa)}")
        print(f"     PTlast in ATR: {_pcts(pl)}")

    # ── [2] MFE reach ────────────────────────────────────────────────
    print("\n[2] MFE REACH (how far price actually ran our way, in R):")
    for style in sorted(by_style, key=lambda s: -len(by_style[s])):
        gs = by_style[style]
        mfes = [g["mfe_r"] for g in gs]
        reach = {x: 100.0 * sum(1 for m in mfes if m >= x) / len(mfes) for x in CF_RUNGS}
        reach_str = "  ".join(f"≥{x}R:{reach[x]:.0f}%" for x in CF_RUNGS)
        print(f"   {style} (n={len(gs)}): med={median(mfes):.2f}R  {reach_str}")

    # ── [3] PT reachability + execution gap ──────────────────────────
    print("\n[3] PT1 REACHABILITY:")
    with_pt = [g for g in geos if g["pt1_progress"] is not None]
    if with_pt:
        prog = [g["pt1_progress"] for g in with_pt]
        touched = [g for g in with_pt if g["pt1_progress"] >= 1.0]
        p80 = sum(1 for p in prog if p >= 0.8)
        p50 = sum(1 for p in prog if p >= 0.5)
        print(f"   median progress toward PT1: {median(prog)*100:.0f}%")
        print(f"   reached ≥50% of PT1: {p50}/{len(prog)} ({100.0*p50/len(prog):.0f}%)")
        print(f"   reached ≥80% of PT1: {p80}/{len(prog)} ({100.0*p80/len(prog):.0f}%)")
        print(f"   TOUCHED PT1 (≥100%): {len(touched)}/{len(prog)} "
              f"({100.0*len(touched)/len(prog):.0f}%)")
        gap = [g for g in touched if "target" not in g["close_reason"].lower()]
        if gap:
            print(f"   ⚠ EXECUTION GAP — touched PT1 but closed otherwise: {len(gap)} row(s)")
            for g in gap[:8]:
                print(f"       {g['symbol']:6s} {g['style']:9s} mfe={g['mfe_r']:+.2f}R "
                      f"pt1={g['pt1_r']:.2f}R realized={g['realized_r'] if g['realized_r'] is not None else float('nan'):+.2f}R "
                      f"close={g['close_reason'][:28]}")

    # ── [4] clock cost ───────────────────────────────────────────────
    print("\n[4] CLOCK COST (eod/decay closes — peak vs realized):")
    clock = [g for g in geos
             if any(k in g["close_reason"].lower() for k in ("eod", "decay"))]
    if clock:
        mfes = [g["mfe_r"] for g in clock]
        rs = [g["realized_r"] for g in clock if g["realized_r"] is not None]
        green_at_peak = sum(1 for g in clock if g["mfe_r"] >= 0.25)
        print(f"   n={len(clock)} clock-closed  med peak MFE={median(mfes):+.2f}R  "
              f"med realized={median(rs) if rs else float('nan'):+.2f}R")
        print(f"   were ≥+0.25R at some point before the clock fired: "
              f"{green_at_peak}/{len(clock)} ({100.0*green_at_peak/len(clock):.0f}%)")
        left = [g["mfe_r"] - g["realized_r"] for g in clock if g["realized_r"] is not None]
        if left:
            print(f"   R left on table (peak − realized): med={median(left):+.2f}R  "
                  f"avg={sum(left)/len(left):+.2f}R")

    # ── [5] counterfactual PT sweep ──────────────────────────────────
    print("\n[5] COUNTERFACTUAL PT SWEEP (exit at +X if MFE reached X, else realized):")
    usable = [g for g in geos if g["realized_r"] is not None]
    base = [g["realized_r"] for g in usable]
    if base:
        print(f"   baseline (actual):        avgR={sum(base)/len(base):+.3f}  "
              f"medR={median(base):+.3f}  win%={100.0*sum(1 for r in base if r>0)/len(base):.0f}  n={len(base)}")
        for x in CF_RUNGS:
            cf = [(x if g["mfe_r"] >= x else g["realized_r"]) for g in usable]
            hit = 100.0 * sum(1 for g in usable if g["mfe_r"] >= x) / len(usable)
            print(f"   PT@{x:.2f}R hit={hit:4.0f}%:  avgR={sum(cf)/len(cf):+.3f}  "
                  f"medR={median(cf):+.3f}  win%={100.0*sum(1 for r in cf if r>0)/len(cf):.0f}")
        print("   (caveat: ignores scale-out partials; MFE precedes close so the")
        print("    path logic is sound for single-exit trades)")

    # ── [6] widest offenders ─────────────────────────────────────────
    print("\n[6] WIDEST PT1 IN DAILY-ATR UNITS (top 10 — the 'OXY 3.1 ATR' club):")
    worst = sorted((g for g in geos if g["pt1_atr"]), key=lambda g: -g["pt1_atr"])[:10]
    for g in worst:
        print(f"   {g['symbol']:6s} {g['style']:9s} {g['setup'][:22]:22s} "
              f"stop={g['stop_atr']:.2f}ATR  PT1={g['pt1_atr']:.2f}ATR  "
              f"mfe={g['mfe_r']:+.2f}R  close={g['close_reason'][:20]}")

    print("\n" + "=" * 78)
    print(f"probe complete {datetime.now(timezone.utc).isoformat()[:19]}Z — no writes")


if __name__ == "__main__":
    main()
