#!/usr/bin/env python3
"""
diag_tqs.py — TQS honesty / data-coverage audit (READ-ONLY)
============================================================

Goal (operator mandate 2026-06-22):
  "make sure all of our TQS scoring metrics are correctly getting the right
   data and using it to produce an HONEST TQS score on every potential trade."

This script reads recent `live_alerts` from the DGX Mongo and dissects each
alert's persisted `tqs_breakdown` (the per-pillar to_dict() the scanner stamps
at scoring time). For every one of the 28 sub-scores across the 5 pillars it
classifies the value as:

  • OK       — a real, data-derived score
  • ABSENT   — the input was genuinely missing; pillar emitted the honest
               "No data" verdict and neutralised the sub-score to 50
  • PROXY    — derived from a weaker stand-in (e.g. EV estimated from R:R,
               verdict "Est. (R:R)") — data-derived but not the real signal
  • DEFAULT  — the SNEAKY case: an absent UPSTREAM input silently fell back to
               a hard-coded default (rsi=50, atr=2.0%, rvol=1.0x, vix=18.0,
               win_rate=0.5, r_capture=75%) that maps to a NORMAL-looking score,
               masking the missing data instead of flagging it.

It then prints, per sub-score: coverage %, distribution (min/median/max/stdev),
and the % of the book that is ABSENT / PROXY / DEFAULT — so we can see exactly
which data pipelines are dark. A stdev≈0 on a sub-score = the pillar is pinned
(frozen) on that input for the whole book.

100% READ-ONLY. No writes, no code edits, no IB calls. Safe to run anytime.

Usage (on the DGX):
    .venv/bin/python diag_tqs.py                 # last 48h (default)
    .venv/bin/python diag_tqs.py --hours 24
    .venv/bin/python diag_tqs.py --symbol NVDA   # one symbol
    .venv/bin/python diag_tqs.py --sample 3      # dump 3 full breakdowns
    .venv/bin/python diag_tqs.py --selftest      # offline parser self-check
"""

import os
import sys
import json
import math
import argparse
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# Sub-score spec: pillar -> [(component_key, display_key)]
# component_key indexes breakdown[pillar]["components"]; display_key indexes
# breakdown[pillar]["display"]. They are the same in current code, but we keep
# them separate to be robust to minor renames across DGX versions.
# ─────────────────────────────────────────────────────────────────────────────
PILLARS = ["setup", "technical", "fundamental", "context", "execution"]

SUBSCORES = {
    "setup":       ["pattern", "win_rate", "expected_value", "tape", "smb"],
    "technical":   ["trend", "rsi", "levels", "volatility", "volume"],
    "fundamental": ["catalyst", "short_interest", "float",
                    "institutional", "earnings", "financial"],
    "context":     ["regime", "relative_strength", "time",
                    "sector", "vix", "day", "ai_model"],
    "execution":   ["history", "tilt", "entry_tendency",
                    "exit_tendency", "streak"],
}

# Numeric sentinels: an upstream input fell back to a hard-coded default that
# the pillar then scored as if it were real data. (pillar, sub) -> fn(raw)->bool
def _approx(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False

DEFAULT_DETECTORS = {
    ("setup", "win_rate"):        lambda r: _approx(r.get("win_rate"), 0.5),
    ("technical", "trend"):       lambda r: str(r.get("ma_stack")) == "neutral",
    ("technical", "rsi"):         lambda r: _approx(r.get("rsi"), 50.0),
    ("technical", "volatility"):  lambda r: _approx(r.get("atr_percent"), 2.0),
    ("technical", "volume"):      lambda r: _approx(r.get("rvol"), 1.0),
    ("context", "vix"):           lambda r: _approx(r.get("vix_level"), 18.0),
    ("execution", "exit_tendency"): lambda r: _approx(r.get("avg_r_capture_pct"), 75.0),
}

# reading substrings that mean "this is a stand-in, not the real signal"
PROXY_HINTS = ("est.", "proxy", "no live")
# reading substrings that mean genuinely-absent even if verdict wasn't "No data"
ABSENT_HINTS = (
    "no data", "no tape", "no clear catalyst", "no short-interest",
    "no float", "no institutional", "no relative-strength", "no model signal",
    "no entry-execution", "no ib financials", "sector data unavailable",
    "limited execution history", "no earnings within",
)


def classify(pillar, sub, comp_score, disp_block, raw):
    """Return one of: ok | absent | proxy | default."""
    verdict = (disp_block or {}).get("verdict", "") or ""
    reading = ((disp_block or {}).get("reading", "") or "").lower()

    if verdict.strip().lower() == "no data":
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


def tech_snapshot_missing(raw):
    """True when the WHOLE technical snapshot fell back to defaults — the most
    dishonest case (a missing snapshot scores ~70, looking like a real read)."""
    if not raw:
        return False
    return (
        _approx(raw.get("rsi"), 50.0)
        and _approx(raw.get("atr_percent"), 2.0)
        and _approx(raw.get("rvol"), 1.0)
        and str(raw.get("ma_stack")) == "neutral"
        and _approx(raw.get("vwap_distance_pct"), 0.0)
    )


# ─────────────────────────────────────────────────────────────────────────────
# stats helpers
# ─────────────────────────────────────────────────────────────────────────────
def _pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _stdev(vals):
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


# ─────────────────────────────────────────────────────────────────────────────
# core analysis
# ─────────────────────────────────────────────────────────────────────────────
def new_acc():
    return {"scores": [], "ok": 0, "absent": 0, "proxy": 0, "default": 0, "missing": 0}


def analyze(alerts):
    """alerts: iterable of dicts (must carry tqs_breakdown). Returns report."""
    acc = {p: {s: new_acc() for s in SUBSCORES[p]} for p in PILLARS}
    pillar_score_acc = {p: [] for p in PILLARS}
    composite = []
    n_total = 0
    n_no_breakdown = 0
    n_tech_snapshot_missing = 0

    for a in alerts:
        n_total += 1
        if a.get("tqs_score") is not None:
            try:
                composite.append(float(a["tqs_score"]))
            except (TypeError, ValueError):
                pass

        bd = a.get("tqs_breakdown") or {}
        if not bd:
            n_no_breakdown += 1
            continue

        # technical snapshot fully-defaulted?
        tech = bd.get("technical") or {}
        if tech_snapshot_missing(tech.get("raw_values") or {}):
            n_tech_snapshot_missing += 1

        for p in PILLARS:
            pd = bd.get(p) or {}
            comps = pd.get("components") or {}
            disp = pd.get("display") or {}
            raw = pd.get("raw_values") or {}
            try:
                if pd.get("score") is not None:
                    pillar_score_acc[p].append(float(pd["score"]))
            except (TypeError, ValueError):
                pass

            for s in SUBSCORES[p]:
                a_acc = acc[p][s]
                if s not in comps:
                    a_acc["missing"] += 1
                    continue
                try:
                    sc = float(comps[s])
                except (TypeError, ValueError):
                    a_acc["missing"] += 1
                    continue
                a_acc["scores"].append(sc)
                kind = classify(p, s, sc, disp.get(s), raw)
                a_acc[kind] += 1

    return {
        "n_total": n_total,
        "n_no_breakdown": n_no_breakdown,
        "n_tech_snapshot_missing": n_tech_snapshot_missing,
        "composite": composite,
        "pillar_scores": pillar_score_acc,
        "subscores": acc,
    }


# ─────────────────────────────────────────────────────────────────────────────
# rendering
# ─────────────────────────────────────────────────────────────────────────────
def _fmt(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def render(rep):
    n = rep["n_total"]
    print("=" * 96)
    print("  TQS DATA-HONESTY AUDIT  —  live_alerts.tqs_breakdown")
    print("=" * 96)
    if n == 0:
        print("\n  No alerts found in the selected window. Widen --hours or check the collection.\n")
        return
    print(f"  Alerts analyzed:        {n}")
    bd_cov = n - rep["n_no_breakdown"]
    print(f"  With tqs_breakdown:     {bd_cov}/{n} ({bd_cov/n*100:.1f}%)"
          f"   (no breakdown: {rep['n_no_breakdown']})")
    tsm = rep["n_tech_snapshot_missing"]
    print(f"  Technical snapshot ALL-DEFAULT (rsi50/atr2/rvol1/neutral): "
          f"{tsm}/{bd_cov} ({(tsm/bd_cov*100) if bd_cov else 0:.1f}%)  "
          f"<- masked as a ~70 score")
    comp = rep["composite"]
    if comp:
        print(f"\n  Composite TQS:  n={len(comp)}  min={_fmt(min(comp))}  "
              f"p50={_fmt(_pct(comp,50))}  max={_fmt(max(comp))}  "
              f"mean={_fmt(sum(comp)/len(comp))}  stdev={_fmt(_stdev(comp),2)}")

    # legend
    print("\n  Legend per sub-score:  COV%=has a numeric score · "
          "ABS=No-data(absent) · PROXY=stand-in · DEF=silent-default(masked) · OK=real")
    print("  ⚠ flags a sub-score where ABSENT+PROXY+DEFAULT >= 50% of the book "
          "or stdev≈0 (pinned).\n")

    hdr = (f"  {'pillar/sub':<34}{'n':>6}{'OK%':>7}{'ABS%':>7}{'PROXY%':>8}"
           f"{'DEF%':>7}{'min':>6}{'p50':>6}{'max':>6}{'sd':>6}")
    worst = []  # (frac_bad, label) for the final verdict

    for p in PILLARS:
        ps = rep["pillar_scores"][p]
        ps_line = ""
        if ps:
            ps_line = (f"   [pillar score: p50={_fmt(_pct(ps,50))} "
                       f"sd={_fmt(_stdev(ps),2)} n={len(ps)}]")
        print("-" * 96)
        print(f"  ▼ {p.upper()}{ps_line}")
        print(hdr)
        for s in SUBSCORES[p]:
            ac = rep["subscores"][p][s]
            scored = len(ac["scores"])
            tot = scored + ac["missing"]
            if tot == 0:
                continue
            cov = scored / tot * 100 if tot else 0
            okp = ac["ok"] / scored * 100 if scored else 0
            absp = ac["absent"] / scored * 100 if scored else 0
            prxp = ac["proxy"] / scored * 100 if scored else 0
            defp = ac["default"] / scored * 100 if scored else 0
            sd = _stdev(ac["scores"])
            bad = absp + prxp + defp
            flag = " ⚠" if (bad >= 50.0 or (scored >= 20 and sd < 0.5)) else ""
            if scored >= 10:
                worst.append((bad, sd, f"{p}.{s}", absp, prxp, defp))
            print(f"  {p+'.'+s:<34}{scored:>6}{okp:>7.0f}{absp:>7.0f}"
                  f"{prxp:>8.0f}{defp:>7.0f}"
                  f"{_fmt(min(ac['scores']),0):>6}{_fmt(_pct(ac['scores'],50),0):>6}"
                  f"{_fmt(max(ac['scores']),0):>6}{_fmt(sd,1):>6}{flag}")

    # ── verdict ──────────────────────────────────────────────────────────
    print("=" * 96)
    print("  VERDICT — where the data pipeline is darkest (sub-scores ranked by "
          "ABSENT+PROXY+DEFAULT %)")
    print("=" * 96)
    worst.sort(key=lambda x: (-x[0], x[1]))
    print(f"  {'sub-score':<30}{'bad%':>7}{'absent%':>9}{'proxy%':>8}"
          f"{'default%':>9}{'stdev':>7}")
    for bad, sd, label, absp, prxp, defp in worst[:14]:
        print(f"  {label:<30}{bad:>7.0f}{absp:>9.0f}{prxp:>8.0f}{defp:>9.0f}{sd:>7.1f}")
    print("\n  Interpretation:")
    print("   • high DEFAULT%  -> an UPSTREAM feed is dark and the pillar is masking")
    print("                       it with a hard-coded default (the dishonest case).")
    print("   • high ABSENT%   -> honestly flagged 'No data' (neutral 50); still a")
    print("                       coverage gap to fill, but the score is not lying.")
    print("   • high PROXY%    -> using a weaker stand-in (e.g. EV from R:R).")
    print("   • stdev ~ 0      -> sub-score is pinned/frozen for the whole book.")
    print("=" * 96)


def dump_samples(alerts, k):
    print("\n" + "#" * 96)
    print(f"#  SAMPLE BREAKDOWNS (first {k})")
    print("#" * 96)
    shown = 0
    for a in alerts:
        if not (a.get("tqs_breakdown")):
            continue
        print(f"\n--- {a.get('symbol','?')} / {a.get('setup_type','?')} "
              f"/ style={a.get('tqs_trade_style', a.get('trade_style','?'))} "
              f"/ TQS={a.get('tqs_score','?')} {a.get('tqs_grade','')} "
              f"/ created_at={a.get('created_at','?')}")
        print(json.dumps(a.get("tqs_breakdown"), indent=2, default=str)[:6000])
        shown += 1
        if shown >= k:
            break
    if shown == 0:
        print("  (no alerts with a tqs_breakdown to sample)")


# ─────────────────────────────────────────────────────────────────────────────
# mongo load
# ─────────────────────────────────────────────────────────────────────────────
def _parse_dt(v):
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def load_alerts(hours, symbol, cap):
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        print("ERROR: MONGO_URL not set in environment.")
        sys.exit(2)
    db_name = os.environ.get("DB_NAME", "tradecommand")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=4000)
    db = client[db_name]
    coll = db["live_alerts"]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()

    proj = {"_id": 0, "symbol": 1, "setup_type": 1, "direction": 1,
            "created_at": 1, "tqs_score": 1, "tqs_grade": 1,
            "tqs_trade_style": 1, "trade_style": 1, "tqs_breakdown": 1,
            "tqs_pillar_scores": 1}
    q = {"created_at": {"$gte": cutoff_iso}}
    if symbol:
        q["symbol"] = symbol.upper()

    rows = list(coll.find(q, proj).sort("created_at", -1).limit(cap))

    # Fallback: created_at stored as datetime (or empty) -> ISO compare missed.
    if not rows:
        base = {"symbol": symbol.upper()} if symbol else {}
        raw = list(coll.find(base, proj).sort("created_at", -1).limit(cap))
        rows = []
        for r in raw:
            dt = _parse_dt(r.get("created_at"))
            if dt is None or dt >= cutoff:
                rows.append(r)
    print(f"  [load] db='{db_name}' coll='live_alerts' window={hours}h "
          f"symbol={symbol or 'ALL'} -> {len(rows)} alerts (cap={cap})")
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# offline self-test (no Mongo) — validates the parser/classifier
# ─────────────────────────────────────────────────────────────────────────────
def selftest():
    def disp(v, r):
        return {"verdict": v, "reading": r}
    # alert 1: lots of dark data
    a1 = {
        "symbol": "TEST1", "setup_type": "breakout", "tqs_score": 52.0,
        "tqs_breakdown": {
            "setup": {"score": 50, "components": {
                "pattern": 55, "win_rate": 50, "expected_value": 47,
                "tape": 50, "smb": 50},
                "display": {
                    "pattern": disp("Neutral", "Breakout · breakout family (est.)"),
                    "win_rate": disp("Neutral", "50% historical win rate"),
                    "expected_value": disp("Neutral", "Est. from 2.0:1 R:R · no live expectancy"),
                    "tape": disp("No data", "No tape-reading data"),
                    "smb": disp("Neutral", "Grade — · 5-var 25/50")},
                "raw_values": {"win_rate": 0.5, "tape_confirmation": False,
                               "smb_grade": "C"}},
            "technical": {"score": 70, "components": {
                "trend": 60, "rsi": 90, "levels": 50, "volatility": 85, "volume": 60},
                "display": {k: disp("Favorable", "x") for k in
                            ["trend", "rsi", "levels", "volatility", "volume"]},
                "raw_values": {"rsi": 50.0, "atr_percent": 2.0, "rvol": 1.0,
                               "ma_stack": "neutral", "vwap_distance_pct": 0.0}},
            "fundamental": {"score": 48, "components": {
                "catalyst": 40, "short_interest": 50, "float": 50,
                "institutional": 50, "earnings": 50, "financial": 50},
                "display": {
                    "catalyst": disp("Caution", "No clear catalyst"),
                    "short_interest": disp("No data", "No short-interest data"),
                    "float": disp("No data", "No float data"),
                    "institutional": disp("No data", "No institutional data"),
                    "earnings": disp("Neutral", "No earnings within 14d"),
                    "financial": disp("No data", "No IB financials")},
                "raw_values": {}},
            "context": {"score": 58, "components": {
                "regime": 55, "relative_strength": 50, "time": 45,
                "sector": 50, "vix": 85, "day": 80, "ai_model": 50},
                "display": {
                    "regime": disp("Neutral", "Range Bound · neutral for longs"),
                    "relative_strength": disp("No data", "No relative-strength data"),
                    "time": disp("Neutral", "Midday"),
                    "sector": disp("No data", "Sector data unavailable"),
                    "vix": disp("Strong", "VIX 18.0 · calm/normal · favorable"),
                    "day": disp("Favorable", "Wednesday"),
                    "ai_model": disp("No data", "No model signal")},
                "raw_values": {"vix_level": 18.0}},
            "execution": {"score": 62, "components": {
                "history": 60, "tilt": 100, "entry_tendency": 50,
                "exit_tendency": 70, "streak": 50},
                "display": {
                    "history": disp("Neutral", "Limited execution history"),
                    "tilt": disp("Strong", "No tilt · 0 consecutive losses"),
                    "entry_tendency": disp("No data", "No entry-execution data yet"),
                    "exit_tendency": disp("Favorable", "R-capture 75%"),
                    "streak": disp("No data", "50% win rate")},
                "raw_values": {"avg_r_capture_pct": 75.0}},
        }}
    # alert 2: healthy data
    a2 = {
        "symbol": "TEST2", "setup_type": "orb", "tqs_score": 74.0,
        "tqs_breakdown": {
            "setup": {"score": 72, "components": {
                "pattern": 80, "win_rate": 75, "expected_value": 90,
                "tape": 82, "smb": 65},
                "display": {
                    "pattern": disp("Favorable", "Orb pattern"),
                    "win_rate": disp("Favorable", "62% historical win rate"),
                    "expected_value": disp("Strong", "Expectancy +1.10R"),
                    "tape": disp("Favorable", "Order-flow confirms setup"),
                    "smb": disp("Favorable", "Grade B · 5-var 32/50")},
                "raw_values": {"win_rate": 0.62, "tape_confirmation": True,
                               "smb_grade": "B"}},
            "technical": {"score": 80, "components": {
                "trend": 90, "rsi": 75, "levels": 80, "volatility": 85, "volume": 90},
                "display": {k: disp("Strong", "x") for k in
                            ["trend", "rsi", "levels", "volatility", "volume"]},
                "raw_values": {"rsi": 42.0, "atr_percent": 2.6, "rvol": 2.3,
                               "ma_stack": "bullish", "vwap_distance_pct": -0.8}},
            "fundamental": {"score": 66, "components": {
                "catalyst": 70, "short_interest": 85, "float": 80,
                "institutional": 70, "earnings": 60, "financial": 72},
                "display": {
                    "catalyst": disp("Favorable", "News catalyst"),
                    "short_interest": disp("Strong", "Short interest 18.0%"),
                    "float": disp("Favorable", "Float 42M"),
                    "institutional": disp("Favorable", "Institutional ownership 55%"),
                    "earnings": disp("Neutral", "No earnings within 14d"),
                    "financial": disp("Favorable", "IB financials (3/4 metrics)")},
                "raw_values": {}},
            "context": {"score": 72, "components": {
                "regime": 90, "relative_strength": 78, "time": 75,
                "sector": 85, "vix": 70, "day": 80, "ai_model": 90},
                "display": {
                    "regime": disp("Strong", "Strong Uptrend · favors longs"),
                    "relative_strength": disp("Favorable", "+3.2% 1d / +5.1% 5d vs QQQ"),
                    "time": disp("Favorable", "Morning Momentum"),
                    "sector": disp("Strong", "Technology · rank 2/11 · leader"),
                    "vix": disp("Favorable", "VIX 16.2 · calm/normal"),
                    "day": disp("Favorable", "Wednesday"),
                    "ai_model": disp("Strong", "Model confirms long (66% conf)")},
                "raw_values": {"vix_level": 16.2}},
            "execution": {"score": 70, "components": {
                "history": 66, "tilt": 100, "entry_tendency": 70,
                "exit_tendency": 90, "streak": 75},
                "display": {
                    "history": disp("Favorable", "Setup exec track record (n=24)"),
                    "tilt": disp("Strong", "No tilt · 0 consecutive losses"),
                    "entry_tendency": disp("Favorable", "Avg entry slippage 0.05%"),
                    "exit_tendency": disp("Strong", "R-capture 84%"),
                    "streak": disp("Favorable", "60% win rate · last 18 closes")},
                "raw_values": {"avg_r_capture_pct": 84.0}},
        }}
    rep = analyze([a1, a2])
    render(rep)
    # assertions
    sa = rep["subscores"]
    assert rep["n_tech_snapshot_missing"] == 1, "expected 1 all-default tech snapshot"
    assert sa["setup"]["expected_value"]["proxy"] == 1, "EV proxy not detected"
    assert sa["setup"]["tape"]["absent"] == 1, "tape absent not detected"
    assert sa["setup"]["win_rate"]["default"] == 1, "win_rate default not detected"
    assert sa["technical"]["rsi"]["default"] == 1, "rsi default not detected"
    assert sa["technical"]["volume"]["default"] == 1, "rvol default not detected"
    assert sa["context"]["vix"]["default"] == 1, "vix default not detected"
    assert sa["context"]["relative_strength"]["absent"] == 1, "RS absent not detected"
    assert sa["fundamental"]["float"]["absent"] == 1, "float absent not detected"
    assert sa["execution"]["entry_tendency"]["absent"] == 1, "entry absent not detected"
    assert sa["execution"]["exit_tendency"]["default"] == 1, "r-capture default not detected"
    # healthy alert should be mostly OK
    assert sa["technical"]["rsi"]["ok"] == 1, "healthy rsi should be ok"
    assert sa["setup"]["expected_value"]["ok"] == 1, "healthy EV should be ok"
    print("\n  ✅ SELFTEST PASSED — classifier + aggregation behave as expected.\n")


def main():
    ap = argparse.ArgumentParser(description="TQS data-honesty audit (read-only)")
    ap.add_argument("--hours", type=int, default=48,
                    help="look-back window in hours (default 48)")
    ap.add_argument("--symbol", type=str, default=None, help="filter one symbol")
    ap.add_argument("--cap", type=int, default=8000,
                    help="max alerts to pull (default 8000)")
    ap.add_argument("--sample", type=int, default=0,
                    help="dump N full breakdowns for eyeballing")
    ap.add_argument("--selftest", action="store_true",
                    help="run offline parser self-check (no Mongo)")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    alerts = load_alerts(args.hours, args.symbol, args.cap)
    rep = analyze(alerts)
    render(rep)
    if args.sample > 0:
        dump_samples(alerts, args.sample)


if __name__ == "__main__":
    main()
