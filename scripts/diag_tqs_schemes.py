#!/usr/bin/env python3
"""
diag_tqs_schemes.py — TQS aggregation A/B/C/D/E comparison (READ-ONLY)
=====================================================================

Recomputes the TQS composite from EXISTING persisted live_alerts.tqs_breakdown
under five aggregation schemes, so we can pick how to score honestly BEFORE
touching the live engine. No writes, no re-scoring, no IB.

Schemes (per the design discussion):
  A  current weighted average                         [baseline]
  B  present-only renormalized average                (drop ABSENT weight)
  C  signed +-10, absent=0, linear back-map           (the "control": ~A, but
                                                        it corrects the pillars'
                                                        non-50 absent values
                                                        (catalyst 40, history 60)
                                                        to TRUE neutral)
  D  signed +-10, present-only, tunable GAIN           (operator's idea, made to
                                                        spread; GAIN=5 == B)
  E  present-only renorm + veto/cap + confirm-bonus    (fatal flaws cap the trade)

Per-sub-score "present vs absent" reuses the diag_tqs classifier:
  present = OK or PROXY (data-derived) · absent = ABSENT or DEFAULT (no real data
  / silently-defaulted). In signed space a sub-score maps s=(comp-50)/5 clamped
  to [-10,+10]; absent -> 0.

INTEGRITY CHECK (printed first): recomputed scheme-A must reproduce the persisted
tqs_score and per-pillar scores. If the mean abs error is large, my hard-coded
sub-weights are stale vs your live engine — paste me the live pillar weighted-sum
lines and I rebase. (As of build: sub-weights mirror v19.34.392 live code.)

USAGE (on the DGX, from repo root):
    .venv/bin/python diag_tqs_schemes.py                     # liquid set, 5d
    .venv/bin/python diag_tqs_schemes.py --symbols TSLA,AAPL --days 10
    .venv/bin/python diag_tqs_schemes.py --all --days 2      # whole book
    .venv/bin/python diag_tqs_schemes.py --gain 8            # tune scheme D
    .venv/bin/python diag_tqs_schemes.py --examples 2        # per-symbol samples
    .venv/bin/python diag_tqs_schemes.py --selftest          # offline math check
"""

import os
import sys
import math
import argparse
from datetime import datetime, timezone, timedelta

# liquid, data-rich default universe
DEFAULT_SYMBOLS = ["TSLA", "MSFT", "AAPL", "MU", "NVDA", "AMD", "META",
                   "AMZN", "GOOGL", "NFLX"]

# sub-score weights WITHIN each pillar — mirror the live *_quality.py code
# (verified against v19.34.392 weighted-sum lines).
SUB_WEIGHTS = {
    "setup":       {"pattern": .20, "win_rate": .15, "expected_value": .30,
                    "tape": .20, "smb": .15},
    "technical":   {"trend": .25, "rsi": .20, "levels": .20,
                    "volatility": .15, "volume": .20},
    "fundamental": {"catalyst": .25, "short_interest": .20, "float": .15,
                    "institutional": .10, "earnings": .10, "financial": .20},
    "context":     {"regime": .22, "relative_strength": .20, "time": .18,
                    "sector": .15, "vix": .12, "ai_model": .10, "day": .03},
    "execution":   {"history": .25, "tilt": .30, "entry_tendency": .15,
                    "exit_tendency": .15, "streak": .15},
}
PILLARS = list(SUB_WEIGHTS.keys())
DEFAULT_PILLAR_WEIGHTS = {"setup": .20, "technical": .25, "fundamental": .15,
                          "context": .20, "execution": .20}

# ── absent/proxy classifier (shared with diag_tqs.py) ──────────────────────
def _approx(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False

DEFAULT_DETECTORS = {
    ("setup", "win_rate"):          lambda r: _approx(r.get("win_rate"), 0.5),
    ("technical", "trend"):         lambda r: str(r.get("ma_stack")) == "neutral",
    ("technical", "rsi"):           lambda r: _approx(r.get("rsi"), 50.0),
    ("technical", "volatility"):    lambda r: _approx(r.get("atr_percent"), 2.0),
    ("technical", "volume"):        lambda r: _approx(r.get("rvol"), 1.0),
    ("context", "vix"):             lambda r: _approx(r.get("vix_level"), 18.0),
    ("execution", "exit_tendency"): lambda r: _approx(r.get("avg_r_capture_pct"), 75.0),
}
PROXY_HINTS = ("est.", "proxy", "no live")
ABSENT_HINTS = (
    "no data", "no tape", "no clear catalyst", "no short-interest",
    "no float", "no institutional", "no relative-strength", "no model signal",
    "no entry-execution", "no ib financials", "sector data unavailable",
    "limited execution history", "no earnings within",
)

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
    if det is not None:
        try:
            if det(raw or {}):
                return "default"
        except Exception:
            pass
    return "ok"

def is_present(kind):
    return kind in ("ok", "proxy")


# ── per-pillar scheme math ─────────────────────────────────────────────────
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def pillar_schemes(pillar, comps, disp, raw, gain):
    """Return dict {A,B,C,D} pillar scores + present/absent breakdown."""
    w = SUB_WEIGHTS[pillar]
    A_num = 0.0          # all subs, persisted value
    Cs_num = 0.0         # signed (all subs, absent->0)
    Bp_num = 0.0; Bp_w = 0.0    # present-only value
    Dp_num = 0.0; Dp_w = 0.0    # present-only signed
    present_keys, absent_keys = [], []
    for sub, wi in w.items():
        if sub not in comps:
            continue
        try:
            c = float(comps[sub])
        except (TypeError, ValueError):
            continue
        kind = classify(pillar, sub, disp.get(sub), raw)
        A_num += wi * c
        if is_present(kind):
            present_keys.append(sub)
            s = _clamp((c - 50.0) / 5.0, -10, 10)
            Cs_num += wi * s
            Bp_num += wi * c; Bp_w += wi
            Dp_num += wi * s; Dp_w += wi
        else:
            absent_keys.append(sub)
            # signed absent -> 0 contributes nothing to Cs_num
    A = A_num
    B = (Bp_num / Bp_w) if Bp_w > 0 else 50.0
    C = _clamp(50.0 + 5.0 * Cs_num, 0, 100)
    d_signed = (Dp_num / Dp_w) if Dp_w > 0 else 0.0
    D = _clamp(50.0 + gain * d_signed, 0, 100)
    return {"A": A, "B": B, "C": C, "D": D,
            "present": present_keys, "absent": absent_keys}


def comp_get(bd, pillar, sub):
    return ((bd.get(pillar) or {}).get("components") or {}).get(sub)


def composite_E(bd, comp_B, pillarsub):
    """B-base + fatal-flaw caps + confirmation bonuses (illustrative)."""
    caps = []
    bonus = 0.0
    notes = []

    def g(p, s):
        return pillarsub.get((p, s))

    # ── caps (fatal flaws) ──
    t_trend = g("technical", "trend")
    if t_trend is not None and t_trend <= 25:
        caps.append(60); notes.append("trend<=25 cap60")
    t_rsi = g("technical", "rsi")
    if t_rsi is not None and t_rsi <= 25:
        caps.append(62); notes.append("rsi<=25 cap62")
    e_tilt = g("execution", "tilt")
    if e_tilt is not None and e_tilt <= 20:
        caps.append(50); notes.append("tilt<=20 cap50")
    e_streak = g("execution", "streak")
    if e_streak is not None and e_streak <= 25:
        caps.append(65); notes.append("streak<=25 cap65")
    # ── confirmation bonuses ──
    s_tape = g("setup", "tape")
    if s_tape is not None and s_tape >= 80:
        bonus += 3; notes.append("tape+3")
    c_rs = g("context", "relative_strength")
    if c_rs is not None and c_rs >= 85:
        bonus += 3; notes.append("rs+3")
    c_sec = g("context", "sector")
    if c_sec is not None and c_sec >= 90:
        bonus += 2; notes.append("sector+2")

    val = comp_B + bonus
    if caps:
        val = min(val, min(caps))
    return _clamp(val, 0, 100), notes


def score_alert(a, gain):
    bd = a.get("tqs_breakdown") or {}
    if not bd:
        return None
    pw = a.get("tqs_weights") or DEFAULT_PILLAR_WEIGHTS
    tw = sum(pw.get(p, 0) for p in PILLARS) or 1.0
    pw = {p: pw.get(p, 0) / tw for p in PILLARS}

    pillar_out = {}
    pillarsub = {}  # (pillar,sub)->present value (for E gates)
    for p in PILLARS:
        pdct = bd.get(p) or {}
        comps = pdct.get("components") or {}
        disp = pdct.get("display") or {}
        raw = pdct.get("raw_values") or {}
        pillar_out[p] = pillar_schemes(p, comps, disp, raw, gain)
        pillar_out[p]["persisted"] = pdct.get("score")
        for sub in SUB_WEIGHTS[p]:
            if sub in comps:
                try:
                    pillarsub[(p, sub)] = float(comps[sub])
                except (TypeError, ValueError):
                    pass

    def composite(key):
        return sum(pw[p] * pillar_out[p][key] for p in PILLARS)

    A, B, C, D = composite("A"), composite("B"), composite("C"), composite("D")
    E, _notes = composite_E(bd, B, pillarsub)
    return {"A": A, "B": B, "C": C, "D": D, "E": E,
            "persisted": a.get("tqs_score"),
            "pillars": pillar_out, "symbol": a.get("symbol"),
            "setup": a.get("setup_type")}


# ── stats ──────────────────────────────────────────────────────────────────
def _pct(v, p):
    if not v:
        return None
    s = sorted(v); k = (len(s) - 1) * p / 100.0
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)

def _stdev(v):
    if len(v) < 2:
        return 0.0
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))

def _band_out(v, lo=45, hi=65):
    if not v:
        return 0.0
    return sum(1 for x in v if x < lo or x > hi) / len(v) * 100


def render(scored, gain):
    print("=" * 100)
    print(f"  TQS AGGREGATION A/B/C/D/E COMPARISON   (n={len(scored)}, scheme-D gain={gain})")
    print("=" * 100)
    if not scored:
        print("  no scored alerts — widen --days or check --symbols")
        return

    # integrity check: recomputed A vs persisted tqs_score
    pairs = [(r["A"], r["persisted"]) for r in scored if r["persisted"] is not None]
    if pairs:
        mae = sum(abs(a - p) for a, p in pairs) / len(pairs)
        mx = max(abs(a - p) for a, p in pairs)
        flag = "✓ faithful" if mae < 1.5 else "⚠ WEIGHTS MAY BE STALE vs live"
        print(f"\n  INTEGRITY: recomputed scheme-A vs persisted tqs_score — "
              f"MAE={mae:.2f}  max={mx:.2f}  ({flag})")
        if mae >= 1.5:
            print("    -> paste me the live *_quality.py weighted-sum lines so I rebase SUB_WEIGHTS.")

    series = {k: [r[k] for r in scored] for k in ("A", "B", "C", "D", "E")}
    print(f"\n  {'scheme':<46}{'min':>6}{'p10':>6}{'p50':>6}{'p90':>6}"
          f"{'max':>6}{'mean':>7}{'stdev':>7}{'%out45-65':>11}")
    labels = {
        "A": "A  current weighted average (baseline)",
        "B": "B  present-only renormalized average",
        "C": "C  signed +-10, absent=0 (control ~A)",
        "D": f"D  signed present-only, gain={gain}",
        "E": "E  renorm + veto/cap + bonus",
    }
    for k in ("A", "B", "C", "D", "E"):
        v = series[k]
        print(f"  {labels[k]:<46}{_pct(v,0):>6.1f}{_pct(v,10):>6.1f}"
              f"{_pct(v,50):>6.1f}{_pct(v,90):>6.1f}{_pct(v,100):>6.1f}"
              f"{sum(v)/len(v):>7.1f}{_stdev(v):>7.2f}{_band_out(v):>11.1f}")
    print("\n  '%out45-65' = share of trades that ESCAPE the dead band — higher = "
          "more discriminating. stdev = spread. Compare A vs the rest.")

    # per-symbol medians
    syms = {}
    for r in scored:
        syms.setdefault(r["symbol"], []).append(r)
    print("\n  " + "-" * 96)
    print(f"  PER-SYMBOL median composite under each scheme")
    print(f"  {'symbol':<10}{'n':>5}{'A':>8}{'B':>8}{'C':>8}{'D':>8}{'E':>8}")
    for sym in sorted(syms, key=lambda s: -len(syms[s])):
        rs = syms[sym]
        med = {k: _pct([r[k] for r in rs], 50) for k in ("A", "B", "C", "D", "E")}
        print(f"  {sym:<10}{len(rs):>5}{med['A']:>8.1f}{med['B']:>8.1f}"
              f"{med['C']:>8.1f}{med['D']:>8.1f}{med['E']:>8.1f}")


def render_examples(scored, k):
    print("\n  " + "=" * 96)
    print(f"  EXAMPLE ALERTS (up to {k} per symbol) — composite under each scheme")
    print("  " + "=" * 96)
    syms = {}
    for r in scored:
        syms.setdefault(r["symbol"], []).append(r)
    for sym in sorted(syms):
        for r in syms[sym][:k]:
            print(f"\n  {sym} / {r['setup']}   persisted={r['persisted']}")
            print(f"      A={r['A']:.1f}  B={r['B']:.1f}  C={r['C']:.1f}  "
                  f"D={r['D']:.1f}  E={r['E']:.1f}")
            for p in PILLARS:
                po = r["pillars"][p]
                ab = (",".join(po["absent"]) or "—")
                print(f"      {p:<12} persisted={str(po['persisted']):>5}  "
                      f"A={po['A']:>5.1f} B={po['B']:>5.1f} C={po['C']:>5.1f} "
                      f"D={po['D']:>5.1f}   absent: {ab}")


# ── load ───────────────────────────────────────────────────────────────────
def _parse_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

def load(db, symbols, days, cap):
    coll = db["live_alerts"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    proj = {"_id": 0, "symbol": 1, "setup_type": 1, "created_at": 1,
            "tqs_score": 1, "tqs_weights": 1, "tqs_breakdown": 1}
    q = {"created_at": {"$gte": cutoff.isoformat()}}
    if symbols:
        q["symbol"] = {"$in": [s.upper() for s in symbols]}
    rows = list(coll.find(q, proj).sort("created_at", -1).limit(cap))
    if not rows:  # datetime-typed created_at fallback
        base = {"symbol": {"$in": [s.upper() for s in symbols]}} if symbols else {}
        raw = list(coll.find(base, proj).sort("created_at", -1).limit(cap))
        rows = [r for r in raw if (_parse_dt(r.get("created_at")) or cutoff) >= cutoff]
    return rows


# ── offline self-test ──────────────────────────────────────────────────────
def selftest(gain):
    def disp(v, r):
        return {"verdict": v, "reading": r}
    # all-present alert -> A==B, C~A (all 50-mapped), D(gain=5)==B
    comps = {"pattern": 80, "win_rate": 70, "expected_value": 60, "tape": 82, "smb": 65}
    dsp = {k: disp("Favorable", "real") for k in comps}
    ps = pillar_schemes("setup", comps, dsp, {}, gain=5)
    assert _approx(ps["A"], ps["B"], 1e-6), (ps["A"], ps["B"])
    assert _approx(ps["A"], ps["C"], 1e-6), (ps["A"], ps["C"])  # all present -> C==A
    assert _approx(ps["B"], ps["D"], 1e-6), (ps["B"], ps["D"])  # gain=5 -> D==B
    print(f"  all-present setup: A={ps['A']:.2f} B={ps['B']:.2f} C={ps['C']:.2f} D(g5)={ps['D']:.2f}  ✓ A==B==C, D==B")

    # one absent sub with a NON-50 persisted value (tape absent=50 here; use catalyst-like)
    comps2 = {"pattern": 80, "win_rate": 70, "expected_value": 60, "tape": 50, "smb": 65}
    dsp2 = dict(dsp); dsp2["tape"] = disp("No data", "No tape-reading data")
    ps2 = pillar_schemes("setup", comps2, dsp2, {}, gain=5)
    # B drops tape(.20); renormalized over .80 of weight
    exp_B = (80*.20 + 70*.15 + 60*.30 + 65*.15) / (.20+.15+.30+.15)
    assert _approx(ps2["B"], exp_B, 1e-6), (ps2["B"], exp_B)
    print(f"  one-absent setup:  A={ps2['A']:.2f} B={ps2['B']:.2f} (renorm over present ✓)")

    # gain amplifies: D(gain=10) spreads further from 50 than D(gain=5) for same input
    p_lo = pillar_schemes("setup", comps, dsp, {}, gain=5)["D"]
    p_hi = pillar_schemes("setup", comps, dsp, {}, gain=10)["D"]
    assert abs(p_hi - 50) > abs(p_lo - 50), (p_lo, p_hi)
    print(f"  gain lever: D(g5)={p_lo:.1f} -> D(g10)={p_hi:.1f}  ✓ higher gain = more spread")
    print("\n  ✅ SELFTEST PASSED — scheme math behaves as designed.\n")


def main():
    ap = argparse.ArgumentParser(description="TQS aggregation A/B/C/D/E comparison")
    ap.add_argument("--symbols", type=str, default=None,
                    help="comma list (default: liquid set). Use --all for whole book.")
    ap.add_argument("--all", action="store_true", help="all symbols")
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--gain", type=float, default=8.0, help="scheme-D gain (5==B)")
    ap.add_argument("--cap", type=int, default=20000)
    ap.add_argument("--examples", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest(args.gain)
        return

    symbols = None
    if not args.all:
        symbols = ([s.strip() for s in args.symbols.split(",")]
                   if args.symbols else DEFAULT_SYMBOLS)

    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set."); sys.exit(2)
    from pymongo import MongoClient
    db = MongoClient(mongo_url, serverSelectionTimeoutMS=4000)[
        os.environ.get("DB_NAME", "tradecommand")]

    rows = load(db, symbols, args.days, args.cap)
    print(f"  [load] symbols={symbols or 'ALL'} days={args.days} -> {len(rows)} alerts")
    scored = [s for s in (score_alert(a, args.gain) for a in rows) if s]
    print(f"  [scored] {len(scored)} alerts carried a usable tqs_breakdown\n")
    render(scored, args.gain)
    if args.examples > 0:
        render_examples(scored, args.examples)
    print("\n" + "=" * 100)


if __name__ == "__main__":
    main()
