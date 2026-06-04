#!/usr/bin/env python3
"""
apply_v19_34_265.py  —  Idempotent applier for v19.34.265
=========================================================
Ships TWO operator-approved changes:

  1. CHART DEPTH BUMP (frontend) — ChartPanel.jsx TIMEFRAMES default
     lookbacks 1/5/10/30/365d  ->  7/14/30/60/365d. The diag probe proved
     storage (86-107d of 1min, 600d+ coarser) and backend cold-load
     (130-521ms) already support this; the shallow values were the sole
     cause of thin + slow-to-populate charts.

  2. BAD-TICK SANITIZATION (backend) — clamp lone corrupt IB prints so a
     single $36-on-$260 tick can't blow out candle autoscale OR the
     volume-profile POC.
       a. routers/sentcom_chart.py  — add `_sanitize_intraday_bars` helper
          + call it after the de-dupe pass (intraday only).
       b. services/smart_levels_service.py — clip `_compute_volume_profile`
          lo/hi to a median-anchored band.

SAFE TO RUN MULTIPLE TIMES. Each edit is guarded by a v19.34.265 marker;
re-runs are no-ops. If an anchor is missing (file already drifted), the
script reports it and makes NO change to that file — it never corrupts.

After it reports OK:
    cd frontend && yarn build           # frontend change goes live
    ./start_backend.sh --force          # backend reload

Run from repo root:
    .venv/bin/python /tmp/apply_v19_34_265.py
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "v19.34.265"


def _repo_root() -> Path:
    for cand in (Path.cwd(),
                 Path.home() / "Trading-and-Analysis-Platform"):
        if (cand / "backend").is_dir() and (cand / "frontend").is_dir():
            return cand
    print("ERROR: could not locate repo root (need ./backend + ./frontend).")
    sys.exit(1)


def _patch(path: Path, old: str, new: str, label: str) -> bool:
    """Return True if a change was written, False if skipped/already-applied."""
    if not path.exists():
        print(f"  ✗ {label}: file not found — {path}")
        return False
    text = path.read_text()
    if new in text:
        print(f"  ⏭  {label}: already applied (no-op)")
        return False
    if old not in text:
        print(f"  ✗ {label}: anchor NOT found — file drifted, skipped (no change)")
        return False
    count = text.count(old)
    if count != 1:
        print(f"  ✗ {label}: anchor matched {count}× (expected 1) — skipped")
        return False
    path.write_text(text.replace(old, new))
    print(f"  ✓ {label}: applied")
    return True


# ── 1. ChartPanel.jsx TIMEFRAMES depth bump ──────────────────────────────
CHART_OLD = """const TIMEFRAMES = [
  { label: '1m',  value: '1min',  daysBack: 1 },
  { label: '5m',  value: '5min',  daysBack: 5 },
  { label: '15m', value: '15min', daysBack: 10 },
  { label: '1h',  value: '1hour', daysBack: 30 },
  { label: '1d',  value: '1day',  daysBack: 365 },
];"""

CHART_NEW = """// v19.34.265 (2026-06-04) — deepened default lookbacks. The
// diag_chart_perf_depth probe confirmed ib_historical_data stores
// 86-107d of 1min and 600d+ of every coarser TF, and the backend
// serves the full target depth cold in 130-521ms. The old shallow
// values (1/5/10/30d) were the sole reason charts felt thin AND slow
// to populate — they forced repeated scroll-triggered lazy-load
// doublings instead of one cheap up-front fetch. Operator targets:
// 1min=7d, 5min=14d, 15min=30d, 1hour=60d, daily=1y.
const TIMEFRAMES = [
  { label: '1m',  value: '1min',  daysBack: 7 },
  { label: '5m',  value: '5min',  daysBack: 14 },
  { label: '15m', value: '15min', daysBack: 30 },
  { label: '1h',  value: '1hour', daysBack: 60 },
  { label: '1d',  value: '1day',  daysBack: 365 },
];"""

# ── 2a. smart_levels_service _compute_volume_profile lo/hi clip ───────────
VP_OLD = '''    if not bars:
        return {"poc_price": None, "hvn_prices": []}
    lo = min(float(b["low"])  for b in bars if b.get("low")  is not None)
    hi = max(float(b["high"]) for b in bars if b.get("high") is not None)
    if not (hi > lo):
        return {"poc_price": None, "hvn_prices": []}'''

VP_NEW = '''    if not bars:
        return {"poc_price": None, "hvn_prices": []}
    # v19.34.265 — transient bad-tick guard. A single corrupt IB print
    # (e.g. a $36 tick on a $260 stock) blows raw min(low)/max(high) out,
    # collapsing bin_size so every real bar's volume lands in one or two
    # bins → a garbage POC for minutes. Clip lo/hi to a band around the
    # MEDIAN close (robust to one outlier) before binning. Each bar's
    # contribution is already clamped to [lo, hi] by the max/min below, so
    # one bad bar's volume just spreads thinly and never moves the POC.
    _closes = sorted(float(b["close"]) for b in bars if b.get("close") is not None)
    _ref = _closes[len(_closes) // 2] if _closes else None
    raw_lo = min(float(b["low"])  for b in bars if b.get("low")  is not None)
    raw_hi = max(float(b["high"]) for b in bars if b.get("high") is not None)
    if _ref and _ref > 0:
        lo = max(raw_lo, _ref * 0.4)
        hi = min(raw_hi, _ref * 2.5)
    else:
        lo, hi = raw_lo, raw_hi
    if not (hi > lo):
        return {"poc_price": None, "hvn_prices": []}'''

# ── 2b-i. sentcom_chart.py — insert helper above the /chart route ─────────
HELPER_ANCHOR = '''@router.get("/chart")
async def get_chart_bars(
    symbol: str = Query(..., min_length=1, max_length=10),
    timeframe: str = Query("5min"),'''

HELPER_NEW = '''def _sanitize_intraday_bars(bars: List[Dict[str, Any]], tol: float = 0.5, win: int = 5):
    """v19.34.265 — transient bad-tick guard for intraday candles.

    A single corrupt IB print (e.g. a $36 tick on a $260 stock) produces a
    bar whose wick/close deviates absurdly from its neighbours, blowing out
    the candle autoscale and squashing every real candle into an unreadable
    band for minutes. Clamp each bar's O/H/L/C into a ±`tol` band around the
    LOCAL median close (±`win` bars). The median is robust to a single
    outlier, so genuine trends/gaps are untouched — only lone spikes get
    clipped. Mutates the dicts in place; returns (bars, fixed_count).
    """
    n = len(bars)
    if n < 3:
        return bars, 0
    closes = [r["close"] for r in bars]   # snapshot BEFORE any mutation
    fixed = 0
    for i, r in enumerate(bars):
        window = sorted(closes[max(0, i - win):min(n, i + win + 1)])
        ref = window[len(window) // 2]
        if ref <= 0:
            continue
        lob, hib = ref * (1.0 - tol), ref * (1.0 + tol)
        o = min(max(r["open"],  lob), hib)
        c = min(max(r["close"], lob), hib)
        h = min(max(r["high"],  lob), hib)
        lw = min(max(r["low"],  lob), hib)
        h = max(h, o, c)        # restore OHLC invariants
        lw = min(lw, o, c)
        if (o, h, lw, c) != (r["open"], r["high"], r["low"], r["close"]):
            r["open"], r["high"], r["low"], r["close"] = o, h, lw, c
            fixed += 1
    return bars, fixed


@router.get("/chart")
async def get_chart_bars(
    symbol: str = Query(..., min_length=1, max_length=10),
    timeframe: str = Query("5min"),'''

# ── 2b-ii. sentcom_chart.py — call the helper after the de-dupe pass ──────
CALL_OLD = '''        else:
            deduped.append(r)
    normalised = deduped'''

CALL_NEW = '''        else:
            deduped.append(r)
    normalised = deduped

    # v19.34.265 — bad-tick sanitization (intraday only; daily bars come
    # from EOD historical and rarely carry transient ticks). Runs BEFORE
    # the session filter + indicator math so a corrupt print can't poison
    # the candle autoscale, EMAs/BB, the volume profile, OR the served
    # bars the frontend renders.
    if tf in {"1min", "5min", "15min", "1hour"} and normalised:
        normalised, _bt_fixed = _sanitize_intraday_bars(normalised)
        if _bt_fixed:
            logger.info(
                "[v19.34.265 bad-tick] %s %s clamped %d outlier bar(s)",
                symbol.upper(), tf, _bt_fixed,
            )'''


def main() -> None:
    root = _repo_root()
    print(f"[apply_v19_34_265] repo root = {root}\n")

    chart_jsx = root / "frontend" / "src" / "components" / "sentcom" / "panels" / "ChartPanel.jsx"
    smart = root / "backend" / "services" / "smart_levels_service.py"
    chart_py = root / "backend" / "routers" / "sentcom_chart.py"

    changed = 0
    print("1) Chart depth bump")
    changed += _patch(chart_jsx, CHART_OLD, CHART_NEW, "ChartPanel.jsx TIMEFRAMES")

    print("\n2a) Volume-profile lo/hi clip")
    changed += _patch(smart, VP_OLD, VP_NEW, "smart_levels_service._compute_volume_profile")

    print("\n2b) Chart bad-tick sanitizer")
    # CALL site first so the HELPER_ANCHOR (the route signature) is still
    # pristine when we insert the helper — order is independent here, but
    # do the unique-call-site edit, then the helper insert.
    changed += _patch(chart_py, CALL_OLD, CALL_NEW, "sentcom_chart.py call-site")
    changed += _patch(chart_py, HELPER_ANCHOR, HELPER_NEW, "sentcom_chart.py helper")

    print("\n" + "=" * 60)
    if changed:
        print(f"DONE — {changed} edit(s) written.")
        print("Next:")
        print("  cd frontend && yarn build      # frontend depth bump")
        print("  ./start_backend.sh --force     # backend sanitizer")
    else:
        print("No changes — everything already at v19.34.265 (or files drifted).")
    print("=" * 60)


if __name__ == "__main__":
    main()
