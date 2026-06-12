#!/usr/bin/env python3
"""
apply_v325b.py — Bracket Geometry Overlay ("reach cone") for the V5 chart
==========================================================================
Operator-approved companion to v325 (HSBG). For the focused symbol with
an open position, the chart now paints:

  • R/R ZONES — translucent red band entry→SL and green band entry→PT1,
    anchored at the entry bar and extending to the hold deadline.
  • REACH CONE — a dotted cyan funnel expanding from the entry bar
    showing the statistically expected price travel for the remaining
    hold window (daily ATR × √time). PTs inside the cone are hittable;
    outside means the bracket demands more movement than the clock
    statistically provides.
  • PT BADGES — "PT1 · 0.62× reach" colored green (≤0.85), amber
    (0.85–1.5), red (>1.5) — the same thresholds as v325's reach gate.
  • CLOCK LINE — dashed pink vertical marker at the decay/EOD deadline.

WHAT CHANGES
------------
backend/routers/sentcom_chart.py
  • NEW `GET /api/sentcom/chart/reach-meta` — daily-ATR% for a symbol
    (collector's symbol_adv_cache.atr_pct, falling back to a 14-bar ATR
    from stored daily bars).

frontend/src/components/sentcom/panels/ChartPanel.jsx
  • New ChartBracketGeometryOverlay component (mirrors the Premarket-
    Shading overlay pattern: absolute SVG, re-projects on pan/zoom).
  • Hold-window math mirrors backend _hsbg_hold_minutes: scalp 60min,
    intraday → remaining session from fill time, swing 10d / multi_day
    5d / position 30d / investment 90d.
  • Renders only when an open position exists for the focused symbol —
    zero footprint otherwise.

Also writes backend/tests/test_v325b_overlay.py.
SAFE TO RUN MULTIPLE TIMES (idempotent).

Run from repo root:  .venv/bin/python /tmp/apply_v325b.py
Then: git add -A && git commit -m "v325b: bracket geometry reach-cone chart overlay" && git push
"""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

BACKEND_REL = "backend/routers/sentcom_chart.py"
FRONTEND_REL = "frontend/src/components/sentcom/panels/ChartPanel.jsx"

BE_CHUNKS = [
    (
        "reach_meta_endpoint",
        '''    return {"success": True, "symbol": sym, "available": available}
''',
        '''    return {"success": True, "symbol": sym, "available": available}


@router.get("/chart/reach-meta")
async def get_chart_reach_meta(
    symbol: str = Query(..., min_length=1, max_length=12),
) -> Dict[str, Any]:
    """v325b — daily-ATR basis for the chart bracket-geometry overlay.

    Returns `atr_pct` (FRACTION of price) preferring the collector's
    symbol_adv_cache (14d daily ATR / close), falling back to a 14-bar
    ATR computed from stored daily bars. The overlay multiplies by the
    entry price to get $ATR and builds the √time reach cone client-side.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    sym = symbol.upper()
    import asyncio as _aio

    def _sync():
        try:
            doc = _db["symbol_adv_cache"].find_one(
                {"symbol": sym}, {"atr_pct": 1, "_id": 0})
            if doc and doc.get("atr_pct"):
                v = float(doc["atr_pct"])
                if 0.001 <= v <= 0.30:
                    return {"atr_pct": round(v, 6), "source": "symbol_adv_cache"}
        except Exception:
            pass
        try:
            rows = list(_db["ib_historical_data"].find(
                {"symbol": sym, "bar_size": "1 day"},
                {"_id": 0, "high": 1, "low": 1, "close": 1, "date": 1},
            ).sort("date", -1).limit(15))
        except Exception:
            rows = []
        if len(rows) >= 5:
            rows.reverse()
            trs = []
            prev_close = None
            for r in rows:
                try:
                    h, l, c = float(r["high"]), float(r["low"]), float(r["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                tr = (h - l) if prev_close is None else max(
                    h - l, abs(h - prev_close), abs(l - prev_close))
                trs.append(tr)
                prev_close = c
            if trs and prev_close:
                atr = sum(trs[-14:]) / len(trs[-14:])
                return {"atr_pct": round(atr / prev_close, 6), "source": "daily_bars"}
        return None

    meta = await _aio.to_thread(_sync)
    if not meta:
        return {"success": False, "symbol": sym, "atr_pct": None, "source": None}
    return {"success": True, "symbol": sym, **meta}
''',
    ),
]

FE_CHUNKS = [
    (
        "reach_meta_state",
        '''  // v324 — per-symbol timeframe availability ({ tfValue: barCount }).
  // null = unknown → all timeframes enabled. Lower-tier symbols without
  // collected 1m/5m history get those buttons grayed out.
  const [availableTfs, setAvailableTfs] = useState(null);
''',
        '''  // v324 — per-symbol timeframe availability ({ tfValue: barCount }).
  // null = unknown → all timeframes enabled. Lower-tier symbols without
  // collected 1m/5m history get those buttons grayed out.
  const [availableTfs, setAvailableTfs] = useState(null);
  // v325b — daily-ATR meta for the bracket-geometry "reach cone" overlay.
  const [reachMeta, setReachMeta] = useState(null);
''',
    ),
    (
        "reach_meta_fetch",
        '''  const MIN_BARS_FOR_TF = 50;
''',
        '''  // v325b — fetch the daily-ATR basis used by the bracket-geometry
  // overlay (reach cone + PT reach badges). Cheap single-doc lookup.
  useEffect(() => {
    let cancelled = false;
    const fetchReachMeta = async () => {
      if (!symbol) { setReachMeta(null); return; }
      try {
        const resp = await safeGet(
          `/api/sentcom/chart/reach-meta?symbol=${encodeURIComponent(symbol)}`,
          { timeout: 6000 },
        );
        if (!cancelled) setReachMeta(resp?.success ? resp : null);
      } catch (_) {
        if (!cancelled) setReachMeta(null);
      }
    };
    fetchReachMeta();
    return () => { cancelled = true; };
  }, [symbol]);

  const MIN_BARS_FOR_TF = 50;
''',
    ),
    (
        "overlay_render",
        '''        <SRLeftLabelsOverlay
          chartRef={chartRef}
          candleSeriesRef={candleSeriesRef}
          leftLabels={leftLabels}
          bars={bars}
        />
      </div>
''',
        '''        <SRLeftLabelsOverlay
          chartRef={chartRef}
          candleSeriesRef={candleSeriesRef}
          leftLabels={leftLabels}
          bars={bars}
        />
        {/* v325b — bracket geometry: R/R zones + √time reach cone +
            PT reach badges + decay/EOD clock line. Renders only when
            an open position exists for the focused symbol. */}
        <ChartBracketGeometryOverlay
          chartRef={chartRef}
          candleSeriesRef={candleSeriesRef}
          bars={normalizedBars}
          position={position}
          reachMeta={reachMeta}
          timeframe={active.value}
        />
      </div>
''',
    ),
    (
        "overlay_component",
        '''      {bands.map((b, i) => (
        <div
          key={i}
          className="absolute top-0 bottom-7 bg-amber-400/15 border-l border-r border-amber-400/40"
          style={{ left: `${b.left}px`, width: `${b.width}px` }}
          title="Premarket session (4:00am-9:30am ET)"
        />
      ))}
    </div>
  );
};
''',
        '''      {bands.map((b, i) => (
        <div
          key={i}
          className="absolute top-0 bottom-7 bg-amber-400/15 border-l border-r border-amber-400/40"
          style={{ left: `${b.left}px`, width: `${b.width}px` }}
          title="Premarket session (4:00am-9:30am ET)"
        />
      ))}
    </div>
  );
};

/**
 * ChartBracketGeometryOverlay — v325b (June 2026)
 * ------------------------------------------------
 * Paints the live bracket geometry for the focused open position:
 *
 *   • R/R zones: translucent red entry→SL, green entry→PT1, anchored at
 *     the entry bar, extending to the hold deadline.
 *   • Reach cone: dotted cyan funnel = entry ± dailyATR×√(elapsed/390),
 *     the statistically expected price travel. PT lines outside the
 *     cone demand more movement than the clock provides.
 *   • PT badges: "PT1 · 0.62× reach" — green ≤0.85, amber ≤1.5, red
 *     beyond (same thresholds as the backend v325 HSBG reach gate).
 *   • Clock line: dashed pink vertical at the decay/EOD deadline.
 *
 * Mirrors the PremarketShadingOverlay pattern: absolutely-positioned
 * layer re-projected via timeScale/priceToCoordinate on every pan/zoom.
 * Hold-window math mirrors backend OpportunityEvaluator._hsbg_hold_minutes.
 */
const GEO_STYLE_HOLD_DAYS = { swing: 10, multi_day: 5, position: 30, investment: 90 };
const GEO_TF_MINUTES = { '1min': 1, '5min': 5, '15min': 15, '1hour': 60, '1day': 390 };

const normalizeGeoStyle = (raw) => {
  const s = String(raw || '').trim().toLowerCase();
  if (s === 'scalp' || s === 'move_2_move') return 'scalp';
  if (GEO_STYLE_HOLD_DAYS[s] != null) return s;
  return 'intraday'; // trade_2_hold / unknown → intraday (matches backend v325)
};

const etMinutesOfDay = (unixSec) => {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', hour12: false, hour: '2-digit', minute: '2-digit',
    }).formatToParts(new Date(unixSec * 1000));
    const h = Number(parts.find(p => p.type === 'hour')?.value);
    const m = Number(parts.find(p => p.type === 'minute')?.value);
    if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
    return h * 60 + m;
  } catch (_) { return null; }
};

const geoRatioColor = (r) => {
  if (r == null) return '#71717a';
  if (r <= 0.85) return '#22c55e';
  if (r <= 1.5) return '#f59e0b';
  return '#ef4444';
};

const ChartBracketGeometryOverlay = ({ chartRef, candleSeriesRef, bars, position, reachMeta, timeframe }) => {
  const [geo, setGeo] = React.useState(null);

  React.useEffect(() => {
    const chart = chartRef?.current;
    const series = candleSeriesRef?.current;
    if (!chart || !series || !position || !Array.isArray(bars) || bars.length < 2) {
      setGeo(null);
      return undefined;
    }
    const entry = Number(position.entry_price ?? position.avg_cost);
    if (!Number.isFinite(entry) || entry <= 0) { setGeo(null); return undefined; }
    const stop = position.stop_price != null ? Number(position.stop_price) : null;
    const targets = (Array.isArray(position.target_prices)
      ? position.target_prices
      : [position.target_price])
      .filter(t => t != null).map(Number).filter(Number.isFinite);
    const atrPct = Number(reachMeta?.atr_pct);
    const dailyAtr = Number.isFinite(atrPct) && atrPct > 0 ? atrPct * entry : null;

    // Entry bar index — first bar at/after the fill time. Fallback when
    // the fill predates the loaded window or the timestamp is missing.
    let entrySec = NaN;
    const rawTs = position.entry_time || position.executed_at || position.created_at;
    if (rawTs) entrySec = Date.parse(rawTs) / 1000;
    let entryIdx = -1;
    if (Number.isFinite(entrySec)) {
      entryIdx = bars.findIndex(b => Number(b.time) >= entrySec);
    }
    if (entryIdx < 0) entryIdx = Math.max(0, bars.length - 30);

    // Hold window in RTH minutes (mirrors backend _hsbg_hold_minutes).
    const style = normalizeGeoStyle(position.trade_style);
    const barMin = GEO_TF_MINUTES[timeframe] || 5;
    let holdMin;
    if (style === 'scalp') {
      holdMin = 60;
    } else if (style === 'intraday') {
      const mod = Number.isFinite(entrySec) ? etMinutesOfDay(entrySec) : null;
      holdMin = mod != null ? Math.min(390, Math.max(15, 16 * 60 - mod)) : 390;
    } else {
      holdMin = (GEO_STYLE_HOLD_DAYS[style] || 10) * 390;
    }
    const holdBars = Math.max(1, Math.round(holdMin / barMin));
    const envelope = dailyAtr != null ? dailyAtr * Math.sqrt(holdMin / 390) : null;

    const recompute = () => {
      try {
        const ts = chart.timeScale();
        const x0 = ts.logicalToCoordinate(entryIdx);
        const xDeadline = ts.logicalToCoordinate(entryIdx + holdBars);
        const yEntry = series.priceToCoordinate(entry);
        if (x0 == null || yEntry == null) { setGeo(null); return; }

        const zoneRight = xDeadline != null ? xDeadline : x0 + 240;
        const zones = [];
        if (stop != null) {
          const ySl = series.priceToCoordinate(stop);
          if (ySl != null) {
            zones.push({ y1: Math.min(yEntry, ySl), y2: Math.max(yEntry, ySl), kind: 'risk' });
          }
        }
        if (targets.length > 0) {
          const yPt = series.priceToCoordinate(targets[0]);
          if (yPt != null) {
            zones.push({ y1: Math.min(yEntry, yPt), y2: Math.max(yEntry, yPt), kind: 'reward' });
          }
        }

        // √time reach cone — ~24 sample points entry → deadline.
        let cone = null;
        if (envelope != null) {
          const steps = 24;
          const up = [];
          const dn = [];
          for (let i = 0; i <= steps; i++) {
            const frac = i / steps;
            const x = ts.logicalToCoordinate(entryIdx + Math.round(holdBars * frac));
            if (x == null) continue;
            const env = dailyAtr * Math.sqrt((holdMin * frac) / 390);
            const yU = series.priceToCoordinate(entry + env);
            const yD = series.priceToCoordinate(entry - env);
            if (yU == null || yD == null) continue;
            up.push(`${x},${yU}`);
            dn.push(`${x},${yD}`);
          }
          if (up.length >= 2) cone = { up: up.join(' '), dn: dn.join(' ') };
        }

        const badges = targets.slice(0, 3).map((tp, i) => {
          const y = series.priceToCoordinate(tp);
          if (y == null) return null;
          const ratio = envelope ? Math.abs(tp - entry) / envelope : null;
          return { y, label: `PT${i + 1}`, ratio };
        }).filter(Boolean);

        let stopBadge = null;
        if (stop != null && envelope) {
          const ySl = series.priceToCoordinate(stop);
          if (ySl != null) stopBadge = { y: ySl, ratio: Math.abs(entry - stop) / envelope };
        }

        setGeo({ x0, zoneRight, xDeadline, zones, cone, badges, stopBadge, style });
      } catch (_) { setGeo(null); }
    };

    recompute();
    let unsub = null;
    try {
      const ts = chart.timeScale();
      const handler = () => recompute();
      ts.subscribeVisibleTimeRangeChange(handler);
      unsub = () => {
        try { ts.unsubscribeVisibleTimeRangeChange(handler); } catch (_) { /* noop */ }
      };
    } catch (_) { /* noop */ }
    return () => { if (unsub) unsub(); };
  }, [chartRef, candleSeriesRef, bars, position, reachMeta, timeframe]);

  if (!geo) return null;
  return (
    <div
      data-testid="chart-bracket-geometry"
      className="pointer-events-none absolute inset-x-0 top-0 bottom-7 overflow-hidden"
    >
      <svg className="absolute inset-0 w-full h-full">
        {geo.zones.map((z, i) => (
          <rect
            key={i}
            x={Math.max(0, geo.x0)}
            y={z.y1}
            width={Math.max(0, geo.zoneRight - Math.max(0, geo.x0))}
            height={Math.max(1, z.y2 - z.y1)}
            fill={z.kind === 'risk' ? 'rgba(239,68,68,0.10)' : 'rgba(34,197,94,0.10)'}
          />
        ))}
        {geo.cone && (
          <>
            <polyline points={geo.cone.up} fill="none" stroke="rgba(56,189,248,0.55)" strokeWidth="1" strokeDasharray="3 3" />
            <polyline points={geo.cone.dn} fill="none" stroke="rgba(56,189,248,0.55)" strokeWidth="1" strokeDasharray="3 3" />
          </>
        )}
        {geo.xDeadline != null && (
          <line x1={geo.xDeadline} x2={geo.xDeadline} y1="0" y2="100%" stroke="rgba(244,114,182,0.5)" strokeWidth="1" strokeDasharray="4 4" />
        )}
      </svg>
      {geo.xDeadline != null && (
        <div
          data-testid="bracket-geometry-clock"
          className="absolute text-[9px] px-1 rounded-sm bg-pink-500/15 text-pink-300 border border-pink-500/30 whitespace-nowrap"
          style={{ left: geo.xDeadline + 3, top: 4 }}
        >
          {geo.style === 'scalp' ? 'decay 60m' : geo.style === 'intraday' ? 'EOD' : `${geo.style} clock`}
        </div>
      )}
      {geo.badges.map((b, i) => (
        <div
          key={i}
          data-testid={`bracket-geometry-pt-badge-${i + 1}`}
          className="absolute text-[10px] font-mono px-1.5 py-0.5 rounded-sm border whitespace-nowrap"
          style={{
            right: 64,
            top: b.y - 9,
            color: geoRatioColor(b.ratio),
            borderColor: 'rgba(63,63,70,0.6)',
            background: 'rgba(9,9,11,0.78)',
          }}
        >
          {b.label}{b.ratio != null ? ` · ${b.ratio.toFixed(2)}× reach` : ''}
        </div>
      ))}
      {geo.stopBadge && (
        <div
          data-testid="bracket-geometry-sl-badge"
          className="absolute text-[10px] font-mono px-1.5 py-0.5 rounded-sm border border-zinc-700/60 text-zinc-400 whitespace-nowrap"
          style={{ right: 64, top: geo.stopBadge.y - 9, background: 'rgba(9,9,11,0.78)' }}
        >
          SL · {geo.stopBadge.ratio.toFixed(2)}×
        </div>
      )}
    </div>
  );
};
''',
    ),
]

TEST_REL = Path("backend") / "tests" / "test_v325b_overlay.py"

TEST_CONTENT = '''"""v325b — bracket geometry overlay static checks."""
import py_compile
from pathlib import Path


def _repo_root():
    for c in Path(__file__).resolve().parents:
        if (c / "backend" / "routers" / "sentcom_chart.py").exists():
            return c
    raise AssertionError("repo root not found")


ROOT = _repo_root()
BE = (ROOT / "backend" / "routers" / "sentcom_chart.py").read_text()
FE = (ROOT / "frontend" / "src" / "components" / "sentcom" / "panels" / "ChartPanel.jsx").read_text()


def test_backend_compiles():
    py_compile.compile(str(ROOT / "backend" / "routers" / "sentcom_chart.py"), doraise=True)


def test_reach_meta_endpoint_present():
    assert '@router.get("/chart/reach-meta")' in BE
    assert "symbol_adv_cache" in BE
    assert "daily_bars" in BE


def test_overlay_component_present():
    assert "ChartBracketGeometryOverlay" in FE
    assert "chart-bracket-geometry" in FE
    assert "reach-meta" in FE
    # Hold-window math mirrors backend _hsbg_hold_minutes
    assert "GEO_STYLE_HOLD_DAYS" in FE
    assert "Math.sqrt(holdMin / 390)" in FE
    # Same thresholds as the v325 reach gate
    assert "0.85" in FE and "1.5" in FE


def test_overlay_wired_into_chart():
    assert FE.count("<ChartBracketGeometryOverlay") == 1
    assert "reachMeta={reachMeta}" in FE
'''


def _find_repo_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / BACKEND_REL).exists() and (cand / FRONTEND_REL).exists():
            return cand
    print("FATAL: run from repo root (backend/ + frontend/ not found)")
    sys.exit(1)


def _apply(path: Path, chunks) -> None:
    text = path.read_text()
    changed = False
    for name, old, new in chunks:
        if new in text:
            print(f"  [SKIP] {name} — already applied")
            continue
        if old not in text:
            print(f"  [FAIL] {name} — anchor not found in {path.name}. ABORTING (no partial writes).")
            sys.exit(2)
        if text.count(old) != 1:
            print(f"  [FAIL] {name} — anchor not unique ({text.count(old)}). ABORTING.")
            sys.exit(2)
        text = text.replace(old, new, 1)
        changed = True
        print(f"  [OK]   {name}")
    if changed:
        path.write_text(text)


def main() -> None:
    root = _find_repo_root()
    print(f"repo root: {root}\n── {BACKEND_REL}")
    _apply(root / BACKEND_REL, BE_CHUNKS)
    print(f"\n── {FRONTEND_REL}")
    _apply(root / FRONTEND_REL, FE_CHUNKS)

    try:
        py_compile.compile(str(root / BACKEND_REL), doraise=True)
        print("\n[OK]   backend py_compile passed")
    except py_compile.PyCompileError as exc:
        print(f"\n[FAIL] backend py_compile FAILED: {exc}")
        sys.exit(3)

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"[OK]   wrote {TEST_REL}")

    print("""
v325b APPLIED.

Next steps:
  1. .venv/bin/python -m pytest backend/tests/test_v325b_overlay.py -q
  2. git add -A && git commit -m "v325b: bracket geometry reach-cone chart overlay" && git push
  3. Restart (commit FIRST — StartTrading.bat runs `git checkout -- .`)
  4. Verify: focus a symbol with an open position — the chart shows the
     red/green R/R zones, the dotted cyan reach cone, "PTn · x.xx× reach"
     badges (green/amber/red), and a dashed pink decay/EOD clock line.
     curl 'http://127.0.0.1:8001/api/sentcom/chart/reach-meta?symbol=SPY'
""")


if __name__ == "__main__":
    main()
