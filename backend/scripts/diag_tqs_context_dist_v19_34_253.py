#!/usr/bin/env python3
"""
v19.34.253 — TQS CONTEXT-PILLAR DE-COMPRESSION DIAGNOSTIC (ship-first).

The `context` pillar is near-constant (prior diag: ~54-70, tiny per-symbol
spread). Root cause: context is ~80% MARKET-LEVEL (regime / time-of-day / VIX /
day-of-week are IDENTICAL across every symbol at a given instant), and its only
two per-symbol inputs (sector fit, AI alignment) frequently default to a flat
50. So there is almost no per-symbol dynamic range.

The fix adds a genuine per-symbol **Relative Strength** component: the stock's
recent return MINUS the return of the index it actually belongs to (QQQ for
Nasdaq-100, SPY for S&P large caps, IWM for Russell/small caps), and reallocates
the dead-weight day-of-week slice into it.

This READ-ONLY diagnostic measures, on live data:
  1. BASELINE context-score distribution from persisted `live_alerts`
     (`tqs_breakdown.context.score`) — proves the current compression.
  2. The per-symbol RS distribution computed from `ib_historical_data` daily
     bars (1d + 5d stock-vs-benchmark returns), plus the benchmark routing
     breakdown (how many symbols → QQQ / SPY / IWM) so routing can be sanity
     checked.
  3. A MODELED context distribution = baseline with the 10% day-of-week weight
     reallocated to an RS sub-score — to show how much spread RS actually adds.

Run on DGX:
    .venv/bin/python backend/scripts/diag_tqs_context_dist_v19_34_253.py --days 14 --universe-cap 400
"""
import argparse
import os
import statistics as st
from collections import Counter
from datetime import datetime, timezone, timedelta

from pymongo import MongoClient  # noqa: E402

# Make the membership SSOT importable when run from repo root.
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.index_symbols import benchmark_for  # noqa: E402

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
db = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)[os.environ.get("DB_NAME", "tradecommand")]
db.client.admin.command("ping")
print(f"[db] {mongo_url}")

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=14, help="lookback for live_alerts baseline")
ap.add_argument("--universe-cap", type=int, default=400, help="max symbols to model RS for")
args = ap.parse_args()


def _dist(vals, label):
    vals = [float(v) for v in vals if v is not None]
    if not vals:
        print(f"  {label:<28} (no data)")
        return None
    vals_sorted = sorted(vals)

    def pct(p):
        return vals_sorted[min(len(vals_sorted) - 1, int(p / 100 * len(vals_sorted)))]
    stdev = st.pstdev(vals) if len(vals) > 1 else 0.0
    print(f"  {label:<28} n={len(vals):<5} mean={st.mean(vals):6.1f} "
          f"stdev={stdev:5.2f} min={min(vals):5.1f} p10={pct(10):5.1f} "
          f"p50={pct(50):5.1f} p90={pct(90):5.1f} max={max(vals):5.1f}")
    return {"n": len(vals), "mean": st.mean(vals), "stdev": stdev,
            "min": min(vals), "max": max(vals)}


# ── daily-bar helper: most recent N closes for a symbol ─────────────────────
def _recent_closes(symbol, n=8):
    rows = list(db["ib_historical_data"].find(
        {"symbol": symbol.upper(), "bar_size": "1 day"},
        {"_id": 0, "date": 1, "close": 1},
    ).sort("date", -1).limit(n))
    return [r.get("close") for r in rows if r.get("close")]


def _ret(closes, lookback):
    """% return over `lookback` sessions (closes are newest-first)."""
    if len(closes) <= lookback or not closes[lookback]:
        return None
    return (closes[0] - closes[lookback]) / closes[lookback] * 100.0


# cache benchmark closes
_bench_cache = {}
def _bench_closes(bench):
    if bench not in _bench_cache:
        _bench_cache[bench] = _recent_closes(bench, 8)
    return _bench_cache[bench]


def rs_score(symbol):
    """Per-symbol RS sub-score 0-100 from 1d+5d stock-minus-benchmark return.
    Returns (score, benchmark, rs_1d, rs_5d) or (None, bench, ..) if no bars."""
    bench = benchmark_for(symbol)
    sc = _recent_closes(symbol, 8)
    bc = _bench_closes(bench)
    if len(sc) < 2 or len(bc) < 2:
        return None, bench, None, None
    rs_1d = (_ret(sc, 1) or 0) - (_ret(bc, 1) or 0)
    rs_5d = (_ret(sc, 5) or 0) - (_ret(bc, 5) or 0) if len(sc) > 5 and len(bc) > 5 else rs_1d
    # Blend (recent weighted) then map ±3% relative outperformance → 0..100,
    # centered at 50. (Tuned later from THIS diag's rs distribution.)
    blended = 0.6 * rs_1d + 0.4 * rs_5d
    score = max(0.0, min(100.0, 50.0 + blended / 3.0 * 50.0))
    return score, bench, rs_1d, rs_5d


# ── 1) BASELINE context from live_alerts ────────────────────────────────────
cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
alerts = list(db["live_alerts"].find(
    {"tqs_breakdown.context.score": {"$exists": True}},
    {"_id": 0, "symbol": 1, "tqs_breakdown.context": 1, "tqs_score": 1}))
ctx_scores = [a.get("tqs_breakdown", {}).get("context", {}).get("score") for a in alerts]

print(f"\n{'='*74}\nTQS CONTEXT DE-COMPRESSION DIAG — {len(alerts)} alerts w/ context\n{'='*74}")
print("\n[1] BASELINE context-pillar distribution (current scoring):")
base = _dist(ctx_scores, "context.score (baseline)")

# ── 2) RS distribution across the live symbol universe ──────────────────────
universe = [a.get("symbol") for a in alerts if a.get("symbol")]
if len(set(universe)) < 30:
    # Broaden with recently-active daily-bar symbols so RS spread is meaningful.
    extra = db["ib_historical_data"].distinct("symbol", {"bar_size": "1 day"})
    universe += list(extra)
universe = list(dict.fromkeys(s.upper() for s in universe))[: args.universe_cap]

print(f"\n[2] Per-symbol RELATIVE STRENGTH (modeled) — universe={len(universe)}:")
rs_vals, bench_counts, missing = [], Counter(), 0
rs_1d_vals = []
for sym in universe:
    score, bench, rs_1d, _ = rs_score(sym)
    bench_counts[bench] += 1
    if score is None:
        missing += 1
        continue
    rs_vals.append(score)
    if rs_1d is not None:
        rs_1d_vals.append(rs_1d)
print(f"  benchmark routing: {dict(bench_counts)}   (no-bars: {missing})")
_dist(rs_vals, "rs_score (0-100, proposed)")
_dist(rs_1d_vals, "rs_1d raw (stock-bench %)")

# ── 3) MODELED context = baseline with 10% day-weight → RS ──────────────────
# Approximation: new_ctx ≈ baseline - 0.10*day_component + 0.10*rs_score.
# day_component is unknown per-alert here, so we model the SPREAD impact by
# mixing 90% baseline + 10% RS across the matched symbols.
print("\n[3] MODELED context with RS reallocation (90% baseline + 10% RS):")
modeled = []
rs_by_sym = {}
for sym in universe:
    s, _, _, _ = rs_score(sym)
    if s is not None:
        rs_by_sym[sym] = s
for a in alerts:
    sym = (a.get("symbol") or "").upper()
    cs = a.get("tqs_breakdown", {}).get("context", {}).get("score")
    if cs is None:
        continue
    rs = rs_by_sym.get(sym)
    modeled.append(0.9 * cs + 0.1 * rs if rs is not None else cs)
mod = _dist(modeled, "context.score (modeled)")

if base and mod:
    print(f"\n  → stdev {base['stdev']:.2f} → {mod['stdev']:.2f} "
          f"({mod['stdev'] - base['stdev']:+.2f}); "
          f"range {base['max']-base['min']:.1f} → {mod['max']-mod['min']:.1f}")
    print("  NOTE: a full rebuild (multi-index regime + RS replacing day-weight,"
          " not just a 10% blend) widens this further. Use the rs_1d/rs_score"
          " distribution above to finalize the ±% → score mapping.\n")
