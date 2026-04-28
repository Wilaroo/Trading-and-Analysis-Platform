/**
 * ChartPanel — Stage 2a of the V5 Command Center rebuild.
 *
 * Minimal shipping version:
 *   - Candles + volume via TradingView `lightweight-charts` v5 (Apache-2.0).
 *   - Timeframe toggle (1m / 5m / 15m / 1h / 1d).
 *   - HTTP fetch of historical bars via /api/hybrid-data/bars/{symbol}.
 *   - Lightweight auto-refresh every N seconds (no WebSocket yet — 2b adds it).
 *   - Zero indicator math yet — 2b wires VWAP / EMA / BB as additional series.
 */
import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts';
import { RefreshCw, TrendingUp, Eye, EyeOff } from 'lucide-react';
import { safeGet } from '../../../utils/api';
import {
  fmtET12Sec,
  chartTickMarkFormatterET,
  chartCrosshairFormatterET,
} from '../../../utils/timeET';
import { useLiveSubscription } from '../../../hooks/useLiveSubscription';

// Supported timeframes. Key = label shown in UI, Value = what the backend API expects.
const TIMEFRAMES = [
  { label: '1m',  value: '1min',  daysBack: 1 },
  { label: '5m',  value: '5min',  daysBack: 5 },
  { label: '15m', value: '15min', daysBack: 10 },
  { label: '1h',  value: '1hour', daysBack: 30 },
  { label: '1d',  value: '1day',  daysBack: 365 },
];

// Indicator overlays. `key` matches the backend `indicators` response map.
// `pane` 0 = main price pane (sub-panes reserved for Stage 2e RSI/MACD).
const INDICATOR_SPECS = [
  { key: 'vwap',      label: 'VWAP',   color: '#fbbf24', width: 2, dash: false, pane: 0 },
  { key: 'ema_20',    label: 'EMA 20', color: '#06b6d4', width: 1, dash: false, pane: 0 },
  { key: 'ema_50',    label: 'EMA 50', color: '#a855f7', width: 1, dash: false, pane: 0 },
  { key: 'ema_200',   label: 'EMA 200',color: '#f43f5e', width: 1, dash: false, pane: 0 },
  { key: 'bb_upper',  label: 'BB↑',    color: 'rgba(139, 92, 246, 0.45)', width: 1, dash: true,  pane: 0 },
  { key: 'bb_middle', label: 'BB·',    color: 'rgba(139, 92, 246, 0.30)', width: 1, dash: true,  pane: 0 },
  { key: 'bb_lower',  label: 'BB↓',    color: 'rgba(139, 92, 246, 0.45)', width: 1, dash: true,  pane: 0 },
];

// Parse any timestamp shape returned by hybrid_data_service into the
// UTCTimestamp (seconds-since-epoch) that lightweight-charts v5 expects.
const toUtcTimestamp = (ts) => {
  if (ts == null) return null;
  if (typeof ts === 'number') return ts > 1e12 ? Math.floor(ts / 1000) : ts;
  const d = new Date(ts);
  const n = d.getTime();
  return Number.isNaN(n) ? null : Math.floor(n / 1000);
};

export const ChartPanel = ({
  symbol = 'SPY',
  initialTimeframe = '5m',
  // 2026-04-28: default to null so the chart fills its flex parent.
  // Legacy callers passing an explicit pixel value still work — see
  // the container <div> render at the bottom of this component.
  height = null,
  autoRefreshMs = 30_000,
  className = '',
  // Optional focused position — if supplied, Entry / SL / PT horizontal
  // price lines are drawn on the chart (V5 Stage 2d-B).
  position = null,
}) => {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const indicatorSeriesRef = useRef({}); // { [key]: ISeriesApi<'Line'> }
  const markersPluginRef = useRef(null); // createSeriesMarkers() plugin api
  const priceLinesRef = useRef([]); // IPriceLine[] — Stage 2d-B (entry/SL/PT overlays)
  const srLinesRef = useRef([]);    // Stage 2e — PDH/PDL/PML support/resistance lines
  // Tracks whether we've performed the initial `fitContent()` call so that
  // subsequent re-renders (auto-refresh, lazy-load backfill) don't reset
  // the user's pan/zoom position.
  const hasFittedRef = useRef(false);
  const [srLevels, setSrLevels] = useState(null);    // { pdh, pdl, pdc, pmh, pml }
  const [showSrLevels, setShowSrLevels] = useState(true);
  const resizeObsRef = useRef(null);
  // 2026-04-28b: cache the most recent normalized bars (with `session`
  // tag) so the PremarketShadingOverlay can compute pixel positions
  // without re-fetching. Stored as a ref to avoid re-renders on every
  // bar tick.
  const lastBarsRef = useRef([]);

  const [timeframe, setTimeframe] = useState(initialTimeframe);
  const [bars, setBars] = useState([]);
  const [indicators, setIndicators] = useState({});
  const [markers, setMarkers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  // How many days of history are currently loaded. Starts at the timeframe
  // default and grows when the user scrolls/zooms past the leftmost bar so
  // older context is fetched on demand (lazy-load).
  const [daysLoaded, setDaysLoaded] = useState(null);
  // Internal flag: true while a backfill (older-history) fetch is in flight.
  // Prevents duplicate fetches when the user keeps scrolling left.
  const backfillInFlightRef = useRef(false);
  // Hard ceiling on how far back we will lazy-load (matches backend cap).
  const MAX_DAYS_BACK = 365;
  // Freshness flags from backend — surface when the chart is rendering stale
  // cache or partial coverage so the user doesn't mistake old bars for live.
  const [staleInfo, setStaleInfo] = useState(null);  // { stale, reason, latest, partial, coverage }
  // Which overlays are visible. Default: VWAP + BB on, all EMAs off (less clutter).
  const [visibleIndicators, setVisibleIndicators] = useState({
    vwap: true,
    ema_20: false,
    ema_50: false,
    ema_200: false,
    bb_upper: true,
    bb_middle: true,
    bb_lower: true,
  });

  const active = useMemo(
    () => TIMEFRAMES.find(t => t.label === timeframe) ?? TIMEFRAMES[1],
    [timeframe]
  );

  // Phase 2: auto-subscribe the focused chart symbol to tick-level pusher
  // feed. Backend ref-counts, so this coexists with Scanner + Modal subs
  // for the same symbol. Cleanup on unmount / symbol change.
  useLiveSubscription(symbol);

  // Initialise chart once
  useEffect(() => {
    if (!containerRef.current) return undefined;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#a1a1aa',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(39, 39, 42, 0.6)' },
        horzLines: { color: 'rgba(39, 39, 42, 0.6)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(82, 82, 91, 0.4)',
        scaleMargins: { top: 0.08, bottom: 0.25 },
      },
      // localization.timeFormatter — controls the crosshair date/time
      // label. We force US Eastern Time, 12-hour clock so the operator
      // sees "9:30 AM" / "1:55 PM" everywhere — never 24-hour military.
      localization: {
        timeFormatter: chartCrosshairFormatterET,
      },
      timeScale: {
        borderColor: 'rgba(82, 82, 91, 0.4)',
        timeVisible: true,
        secondsVisible: false,
        // tickMarkFormatter — the labels stamped along the x-axis.
        // Same ET-12h normalization as the crosshair.
        tickMarkFormatter: chartTickMarkFormatterET,
      },
      crosshair: {
        mode: 1,
        vertLine:  { color: '#06b6d4', width: 1, style: 3, labelBackgroundColor: '#0e7490' },
        horzLine:  { color: '#06b6d4', width: 1, style: 3, labelBackgroundColor: '#0e7490' },
      },
      autoSize: true,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#f43f5e',
      borderUpColor: '#10b981',
      borderDownColor: '#f43f5e',
      wickUpColor: '#10b981',
      wickDownColor: '#f43f5e',
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      color: 'rgba(6, 182, 212, 0.35)',
    });
    // Bottom 18% of the pane is reserved for volume
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    // Create one LineSeries per indicator overlay up front. Visibility is
    // toggled later via `applyOptions({ visible })` rather than add/remove,
    // so series order + colours stay stable.
    indicatorSeriesRef.current = {};
    for (const spec of INDICATOR_SPECS) {
      const s = chart.addSeries(LineSeries, {
        color: spec.color,
        lineWidth: spec.width,
        lineStyle: spec.dash ? 2 : 0, // 0 = solid, 2 = dashed
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        visible: true, // overridden by effect below
      });
      indicatorSeriesRef.current[spec.key] = s;
    }

    // Trade markers plugin — attached to the candle series so arrows render
    // on price bars. Stage 2c adds executed entry/exit markers; later stages
    // will extend this with setup-trigger pins.
    try {
      markersPluginRef.current = createSeriesMarkers(candleSeries, []);
    } catch (err) {
      // Older lightweight-charts versions exposed markers via
      // series.setMarkers(). We fall back silently if createSeriesMarkers
      // isn't available in this build.
      markersPluginRef.current = null;
    }

    // Resize tracking is handled by `autoSize: true` on the chart
    // (lightweight-charts >= v4.4) — no manual ResizeObserver needed.
    // We still create one purely to invalidate priceScale margins on
    // height changes, since some v5 builds don't recompute the volume
    // pane on auto-resize.
    const ro = new ResizeObserver(() => {
      try {
        const candleScale = candleSeries.priceScale();
        candleScale.applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });
        const volScale = volumeSeries.priceScale();
        volScale.applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      } catch (_) { /* noop */ }
    });
    ro.observe(containerRef.current);
    resizeObsRef.current = ro;

    return () => {
      try { ro.disconnect(); } catch (_) { /* ignore */ }
      try { chart.remove(); } catch (_) { /* ignore */ }
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [height]);

  // Reset the lazy-load window whenever the timeframe changes — each
  // timeframe has its own sensible default. Also reset the "fit" flag so
  // the new dataset gets framed once before lazy-loading takes over.
  useEffect(() => {
    setDaysLoaded(active.daysBack);
    hasFittedRef.current = false;
  }, [active.daysBack]);

  // Reset the fit flag when the symbol changes too — otherwise switching
  // symbols would inherit the previous symbol's pan position.
  useEffect(() => { hasFittedRef.current = false; }, [symbol]);

  // Fetch bars for current symbol + timeframe. Honours the lazy-loaded
  // `daysLoaded` window so subsequent refetches keep older bars on screen.
  const fetchBars = useCallback(async () => {
    if (!symbol) return;
    const days = daysLoaded || active.daysBack;
    setLoading(true);
    setError(null);
    try {
      const resp = await safeGet(
        `/api/sentcom/chart?symbol=${encodeURIComponent(symbol)}` +
        `&timeframe=${encodeURIComponent(active.value)}&days=${days}`
      );
      if (!resp) {
        setError('Bar fetch failed');
        return;
      }
      if (resp.success === false) {
        setError(resp.error || 'Backend returned no bars');
        setBars([]);
        setIndicators({});
        setMarkers([]);
        return;
      }
      const fetchedBars = Array.isArray(resp.bars) ? resp.bars : [];
      setBars(fetchedBars);
      setIndicators(resp.indicators && typeof resp.indicators === 'object' ? resp.indicators : {});
      setMarkers(Array.isArray(resp.markers) ? resp.markers : []);
      setStaleInfo({
        stale: !!resp.stale,
        reason: resp.stale_reason || null,
        latest: resp.latest_available_date || null,
        partial: !!resp.partial,
        coverage: typeof resp.coverage === 'number' ? resp.coverage : null,
      });
      setLastUpdated(Date.now());
    } catch (err) {
      setError(err?.message || 'Failed to fetch bars');
    } finally {
      setLoading(false);
      backfillInFlightRef.current = false;
    }
  }, [symbol, active, daysLoaded]);

  // Refetch whenever symbol / timeframe changes
  useEffect(() => { fetchBars(); }, [fetchBars]);

  // Auto-refresh (lightweight — 2b will replace with a WS subscription)
  useEffect(() => {
    if (!autoRefreshMs) return undefined;
    const id = setInterval(fetchBars, autoRefreshMs);
    return () => clearInterval(id);
  }, [fetchBars, autoRefreshMs]);

  // Push data into the series whenever bars change
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;
    if (!bars.length) {
      candleSeriesRef.current.setData([]);
      volumeSeriesRef.current.setData([]);
      return;
    }
    // Bars must be sorted ascending AND strictly unique by time for
    // lightweight-charts — duplicates throw
    //   "Assertion failed: data must be asc ordered by time, index=N,
    //    time=T, prev time=T"
    // which used to crash the whole Command Center. Duplicates can legit
    // surface after a chunked backfill merges overlapping windows (e.g.
    // the last bar of chunk N shares its timestamp with the first bar of
    // chunk N+1 at a session boundary). De-dupe by keeping the last
    // occurrence — that's the freshest copy of the row.
    const rows = bars
      .map(b => ({
        time: toUtcTimestamp(b.timestamp ?? b.date ?? b.time),
        open: Number(b.open),
        high: Number(b.high),
        low:  Number(b.low),
        close: Number(b.close),
        volume: Number(b.volume ?? 0),
      }))
      .filter(r => r.time != null && Number.isFinite(r.open))
      .sort((a, b) => a.time - b.time)
      .reduce((acc, r) => {
        const last = acc[acc.length - 1];
        if (last && last.time === r.time) {
          acc[acc.length - 1] = r;    // keep the freshest duplicate
        } else {
          acc.push(r);
        }
        return acc;
      }, []);

    const candleData = rows.map(({ time, open, high, low, close }) => (
      { time, open, high, low, close }
    ));
    const volumeData = rows.map(({ time, open, close, volume }) => ({
      time,
      value: volume,
      color: close >= open
        ? 'rgba(16, 185, 129, 0.35)'
        : 'rgba(244, 63, 94, 0.35)',
    }));

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
    // 2026-04-28b: stash bars (with `session` tag from backend) so the
    // PremarketShadingOverlay can compute the contiguous premarket
    // pixel ranges without a separate API call.
    lastBarsRef.current = rows;
    // Fit the newly loaded range only on the first load. Subsequent
    // re-fetches (auto-refresh, lazy-load backfill) preserve whatever
    // pan/zoom the user already has so the chart doesn't snap back.
    if (!hasFittedRef.current) {
      try { chartRef.current?.timeScale().fitContent(); } catch (_) { /* noop */ }
      hasFittedRef.current = true;
    }
  }, [bars]);

  // Lazy-load older history when user scrolls/pans/zooms past the leftmost
  // loaded bar. Uses lightweight-charts `subscribeVisibleLogicalRangeChange`
  // which fires on every pan + scroll-wheel zoom. When the visible logical
  // range's `from` index goes below a small threshold (i.e. user is near
  // the leftmost bar), we double the loaded window (capped at MAX_DAYS_BACK)
  // and refetch — preserving on-screen position via the unchanged time
  // scale visible range.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return undefined;

    const handleRangeChange = (range) => {
      if (!range) return;
      if (backfillInFlightRef.current) return;
      if (loading) return;
      // `from` is a fractional logical index. Negative means the user has
      // panned past the leftmost loaded bar. Anything within the first
      // 5 bars also triggers a backfill so the chart never feels capped.
      const threshold = 5;
      if (range.from > threshold) return;
      if (!daysLoaded) return;
      if (daysLoaded >= MAX_DAYS_BACK) return;
      const next = Math.min(MAX_DAYS_BACK, daysLoaded * 2);
      if (next === daysLoaded) return;
      backfillInFlightRef.current = true;
      setDaysLoaded(next);
    };

    try {
      chart.timeScale().subscribeVisibleLogicalRangeChange(handleRangeChange);
    } catch (_) { /* noop */ }
    return () => {
      try {
        chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleRangeChange);
      } catch (_) { /* noop */ }
    };
  }, [daysLoaded, loading]);

  // Push indicator series data whenever `indicators` changes.
  useEffect(() => {
    for (const spec of INDICATOR_SPECS) {
      const series = indicatorSeriesRef.current[spec.key];
      if (!series) continue;
      const points = Array.isArray(indicators[spec.key]) ? indicators[spec.key] : [];
      // Same ascending-unique contract as the candle series — dedupe by
      // time so a stray duplicate can't crash the whole Command Center.
      const cleaned = points
        .map(p => ({ time: Number(p.time), value: Number(p.value) }))
        .filter(p => Number.isFinite(p.time) && Number.isFinite(p.value))
        .sort((a, b) => a.time - b.time)
        .reduce((acc, p) => {
          const last = acc[acc.length - 1];
          if (last && last.time === p.time) acc[acc.length - 1] = p;
          else acc.push(p);
          return acc;
        }, []);
      series.setData(cleaned);
    }
  }, [indicators]);

  // Apply visibility whenever the toggle state changes (cheap, no re-setData).
  useEffect(() => {
    for (const spec of INDICATOR_SPECS) {
      const series = indicatorSeriesRef.current[spec.key];
      if (!series) continue;
      try {
        series.applyOptions({ visible: !!visibleIndicators[spec.key] });
      } catch (_) {
        /* series may have been removed during unmount */
      }
    }
  }, [visibleIndicators]);

  // Push executed-trade markers onto the candle series.
  useEffect(() => {
    const plugin = markersPluginRef.current;
    if (!plugin) return;
    try {
      // lightweight-charts also requires markers to be ascending; dedup is
      // NOT required here (same time can have buy+sell markers), only sort.
      plugin.setMarkers(
        markers
          .map(m => ({ ...m, time: Number(m.time) }))
          .filter(m => Number.isFinite(m.time))
          .sort((a, b) => a.time - b.time)
      );
    } catch (_) {
      /* markers plugin api may not be ready on first render */
    }
  }, [markers]);

  // Stage 2d-B — draw Entry / Stop-Loss / Profit-Target horizontal lines when
  // a focused position is supplied. Clears previous lines on every change so
  // we never leak stale levels.
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return undefined;
    // Tear down any previously drawn lines
    for (const line of priceLinesRef.current) {
      try { series.removePriceLine(line); } catch (_) { /* noop */ }
    }
    priceLinesRef.current = [];

    if (!position) return undefined;
    const dir = (position.direction || position.side || '').toLowerCase();
    const specs = [];
    if (position.entry_price != null) {
      specs.push({ price: Number(position.entry_price), color: '#eab308', title: `E ${Number(position.entry_price).toFixed(2)}`, lineStyle: 1 });
    }
    if (position.stop_price != null) {
      specs.push({ price: Number(position.stop_price), color: '#ef4444', title: `SL ${Number(position.stop_price).toFixed(2)}`, lineStyle: 2 });
    }
    // Support both singular `target_price` (legacy) and `target_prices` array
    // (bot trades with scale-out levels). Paint each as its own PT line.
    const targets = Array.isArray(position.target_prices)
      ? position.target_prices.filter(t => t != null)
      : (position.target_price != null ? [position.target_price] : []);
    targets.forEach((tp, i) => {
      specs.push({
        price: Number(tp),
        color: '#22c55e',
        title: targets.length > 1 ? `PT${i + 1} ${Number(tp).toFixed(2)}` : `PT ${Number(tp).toFixed(2)}`,
        lineStyle: 2,
      });
    });

    for (const spec of specs) {
      if (!Number.isFinite(spec.price)) continue;
      try {
        const line = series.createPriceLine({
          price: spec.price,
          color: spec.color,
          lineWidth: 1,
          lineStyle: spec.lineStyle,
          axisLabelVisible: true,
          title: spec.title,
        });
        priceLinesRef.current.push(line);
      } catch (_) { /* unsupported in this chart build */ }
    }

    return () => {
      for (const line of priceLinesRef.current) {
        try { series.removePriceLine(line); } catch (_) { /* noop */ }
      }
      priceLinesRef.current = [];
    };
  }, [position?.entry_price, position?.stop_price, position?.target_price, position?.target_prices, position?.direction, position?.side]);

  // Stage 2e — fetch PDH / PDL / PDC / PMH / PML for the current symbol
  // and paint them as horizontal support/resistance price lines.
  useEffect(() => {
    let cancelled = false;
    const fetchLevels = async () => {
      if (!symbol) return;
      try {
        const resp = await safeGet(
          `/api/sentcom/chart/levels?symbol=${encodeURIComponent(symbol)}`,
          { timeout: 5000 },
        );
        if (!cancelled) {
          setSrLevels(resp?.levels || null);
        }
      } catch (_) {
        if (!cancelled) setSrLevels(null);
      }
    };
    fetchLevels();
    return () => { cancelled = true; };
  }, [symbol]);

  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return undefined;
    // Clear any previous SR lines
    for (const line of srLinesRef.current) {
      try { series.removePriceLine(line); } catch (_) { /* noop */ }
    }
    srLinesRef.current = [];
    if (!srLevels || !showSrLevels) return undefined;

    const specs = [
      { key: 'pdh', label: 'PDH', color: 'rgba(239, 68, 68, 0.65)',  style: 3 }, // dotted red
      { key: 'pdl', label: 'PDL', color: 'rgba(34, 197, 94, 0.65)',  style: 3 }, // dotted green
      { key: 'pdc', label: 'PDC', color: 'rgba(148, 163, 184, 0.55)', style: 1 }, // solid slate
      { key: 'pmh', label: 'PMH', color: 'rgba(249, 115, 22, 0.55)', style: 3 }, // dotted orange
      { key: 'pml', label: 'PML', color: 'rgba(59, 130, 246, 0.55)', style: 3 }, // dotted blue
    ];

    for (const spec of specs) {
      const price = srLevels[spec.key];
      if (price == null) continue;  // guard against null BEFORE Number() which turns null → 0
      const num = Number(price);
      if (!Number.isFinite(num) || num <= 0) continue;
      try {
        const line = series.createPriceLine({
          price: num,
          color: spec.color,
          lineWidth: 1,
          lineStyle: spec.style,
          axisLabelVisible: true,
          title: `${spec.label} ${num.toFixed(2)}`,
        });
        srLinesRef.current.push(line);
      } catch (_) { /* noop */ }
    }

    return () => {
      for (const line of srLinesRef.current) {
        try { series.removePriceLine(line); } catch (_) { /* noop */ }
      }
      srLinesRef.current = [];
    };
  }, [srLevels, showSrLevels]);

  const toggleIndicator = useCallback((key) => {
    setVisibleIndicators(prev => ({ ...prev, [key]: !prev[key] }));
  }, []);

  return (
    <div
      data-testid="sentcom-chart-panel"
      className={`relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-zinc-950/90 via-zinc-950/80 to-zinc-900/80 backdrop-blur-xl ${
        // 2026-04-28c: when no fixed `height` prop is passed (V5 default),
        // the panel must be a flex column that fills its parent — otherwise
        // the inner `chart-container` with `flex-1 min-h-0` collapses to 0px
        // because the root isn't a flex parent. This caused the empty chart
        // pane the operator screenshotted on 2026-04-28.
        height ? '' : 'flex flex-col h-full'
      } ${className}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/5 gap-4 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <TrendingUp className="w-4 h-4 text-cyan-400" />
          <span
            data-testid="chart-symbol"
            className="text-sm font-semibold text-zinc-100 tracking-tight"
          >
            {symbol}
          </span>
          <span className="text-[10px] uppercase tracking-wider text-zinc-500">
            {active.label} bars
          </span>
          {lastUpdated && !loading && (
            <span className="text-[10px] text-zinc-600 truncate">
              · updated {fmtET12Sec(lastUpdated)} ET
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Indicator toggles */}
          <div className="flex items-center gap-1" data-testid="chart-indicator-toggles">
            {INDICATOR_SPECS.map((spec) => {
              const on = !!visibleIndicators[spec.key];
              return (
                <button
                  key={spec.key}
                  data-testid={`chart-indicator-${spec.key}`}
                  onClick={() => toggleIndicator(spec.key)}
                  title={`Toggle ${spec.label}`}
                  className={`flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                    on
                      ? 'text-zinc-100 bg-white/5 ring-1 ring-white/10'
                      : 'text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: spec.color, opacity: on ? 1 : 0.4 }}
                  />
                  <span>{spec.label}</span>
                  {on
                    ? <Eye className="w-3 h-3 opacity-60" />
                    : <EyeOff className="w-3 h-3 opacity-40" />}
                </button>
              );
            })}
            {/* Stage 2e — PDH/PDL/PML support/resistance toggle */}
            <button
              data-testid="chart-sr-toggle"
              onClick={() => setShowSrLevels((v) => !v)}
              title="Toggle PDH / PDL / PMH / PML support-resistance lines"
              className={`flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded transition-colors ml-1 ${
                showSrLevels
                  ? 'text-zinc-100 bg-white/5 ring-1 ring-white/10'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: '#f59e0b', opacity: showSrLevels ? 1 : 0.4 }}
              />
              <span>S/R</span>
              {showSrLevels
                ? <Eye className="w-3 h-3 opacity-60" />
                : <EyeOff className="w-3 h-3 opacity-40" />}
            </button>
          </div>

          {/* Timeframe + refresh */}
          <div className="flex items-center gap-1">
            {TIMEFRAMES.map((t) => (
              <button
                key={t.label}
                data-testid={`chart-timeframe-${t.label}`}
                onClick={() => setTimeframe(t.label)}
                className={`px-2.5 py-0.5 text-[11px] rounded-md transition-colors ${
                  t.label === timeframe
                    ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-400/30'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/5'
                }`}
              >
                {t.label}
              </button>
            ))}
            <button
              data-testid="chart-refresh"
              onClick={fetchBars}
              className="ml-2 p-1 text-zinc-500 hover:text-zinc-200 transition-colors"
              aria-label="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Chart container.
          2026-04-28b: the chart uses `autoSize: true` and reads its
          dimensions from this container's bounding box. Container MUST
          have an explicit min-height (160px) and `position: relative`
          so the premarket-shading overlay (drawn as an absolute-
          positioned sibling) lines up correctly.
          When `height` prop is omitted (V5 default), `flex-1 min-h-0`
          fills the parent. When passed (legacy), it's honoured inline. */}
      <div
        data-testid="chart-container"
        className={height ? 'relative' : 'flex-1 min-h-0 relative'}
        style={
          height
            ? { height, width: '100%', minHeight: 240 }
            : { width: '100%', minHeight: 240 }
        }
      >
        <div
          ref={containerRef}
          style={{ width: '100%', height: '100%' }}
        />
        {/* Premarket session shading overlay (added 2026-04-28b).
            Operator request: pre-market bars must be visually
            distinct from RTH bars. We render a translucent strip
            absolutely positioned over the chart canvas, computing
            x-coordinates from the chart's time scale. */}
        <PremarketShadingOverlay
          chartRef={chartRef}
          bars={lastBarsRef.current}
        />
      </div>

      {/* Overlays: loading / empty / error states */}
      {loading && !bars.length && (
        <div
          data-testid="chart-loading"
          className="absolute inset-0 flex items-center justify-center bg-black/20"
        >
          <span className="text-xs text-zinc-400">Loading bars...</span>
        </div>
      )}
      {!loading && !bars.length && !error && (
        <div
          data-testid="chart-empty"
          className="absolute inset-x-0 top-12 flex items-center justify-center text-xs text-zinc-500"
        >
          No bars available for {symbol} on {active.label}.
        </div>
      )}
      {error && (
        <div
          data-testid="chart-error"
          className="absolute inset-x-0 top-12 flex items-center justify-center text-xs text-rose-400"
        >
          {error}
        </div>
      )}
      {!error && staleInfo?.stale && bars.length > 0 && (
        <div
          data-testid="chart-stale-banner"
          className="absolute top-2 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-1 rounded-full border border-amber-500/50 bg-amber-500/10 text-[10px] uppercase tracking-wider text-amber-300"
          title={`Historical collector hasn't written fresh bars. Reason: ${staleInfo.reason || 'unknown'}`}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
          STALE CACHE
          {staleInfo.latest && (
            <span className="text-amber-200/80 normal-case tracking-normal">
              · latest {String(staleInfo.latest).slice(0, 10)}
            </span>
          )}
        </div>
      )}
      {!error && !staleInfo?.stale && staleInfo?.partial && bars.length > 0 && (
        <div
          data-testid="chart-partial-banner"
          className="absolute top-2 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-1 rounded-full border border-sky-500/50 bg-sky-500/10 text-[10px] uppercase tracking-wider text-sky-300"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
          PARTIAL · {Math.round((staleInfo.coverage || 0) * 100)}% coverage
        </div>
      )}
    </div>
  );
};

export default ChartPanel;


/**
 * PremarketShadingOverlay
 * ------------------------
 * Renders translucent vertical bands over premarket bars (4:00am-9:30am
 * ET) so the operator can visually distinguish premarket prints from
 * regular-hours prints. Added 2026-04-28 per operator request:
 *   "have the pre market session with background shading so i know
 *    the difference easier visually."
 *
 * How it works:
 *   1. Reads the bars passed in (each tagged `session: 'pre' | 'rth'`
 *      by the backend `/api/sentcom/chart` endpoint).
 *   2. Walks the bar list to find contiguous runs of session='pre'
 *      and merges each run into a {start, end} range.
 *   3. On every visible-time-range change (pan/zoom) it re-projects
 *      each range into pixel coordinates via
 *      `chart.timeScale().timeToCoordinate()` and draws an absolutely-
 *      positioned <div> band per range.
 *
 * Returns null if the chart isn't ready yet — safe to render even
 * before chartRef.current is wired.
 */
const PremarketShadingOverlay = ({ chartRef, bars }) => {
  const [bands, setBands] = React.useState([]);

  React.useEffect(() => {
    const chart = chartRef?.current;
    if (!chart) return undefined;
    if (!Array.isArray(bars) || bars.length === 0) {
      setBands([]);
      return undefined;
    }

    // Build {startTime, endTime} ranges from contiguous premarket runs.
    const ranges = [];
    let runStart = null;
    let runEnd = null;
    for (const b of bars) {
      if (b?.session === 'pre' && b.time != null) {
        if (runStart == null) runStart = b.time;
        runEnd = b.time;
      } else if (runStart != null) {
        ranges.push({ startTime: runStart, endTime: runEnd });
        runStart = null;
        runEnd = null;
      }
    }
    if (runStart != null) ranges.push({ startTime: runStart, endTime: runEnd });

    if (ranges.length === 0) {
      setBands([]);
      return undefined;
    }

    const recompute = () => {
      try {
        const ts = chart.timeScale();
        const next = [];
        for (const r of ranges) {
          const x1 = ts.timeToCoordinate(r.startTime);
          const x2 = ts.timeToCoordinate(r.endTime);
          if (x1 == null || x2 == null) continue;
          // Pad ±1.5px so the band visually wraps the candle wicks.
          const left = Math.min(x1, x2) - 1.5;
          const width = Math.abs(x2 - x1) + 3;
          if (width <= 0) continue;
          next.push({ left, width });
        }
        setBands(next);
      } catch (_) { /* chart torn down */ }
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

    return () => {
      if (unsub) unsub();
    };
  }, [chartRef, bars]);

  if (!bands.length) return null;
  return (
    <div
      data-testid="chart-premarket-shading"
      className="pointer-events-none absolute inset-0"
      // Container must NOT cover the time-axis row at the bottom — the
      // chart leaves ~28px there. We bound the overlay to the candle
      // pane only by leaving the bottom inset on `inset-0` defaults.
    >
      {bands.map((b, i) => (
        <div
          key={i}
          className="absolute top-0 bottom-7 bg-amber-400/8 border-l border-r border-amber-400/20"
          style={{ left: `${b.left}px`, width: `${b.width}px` }}
          title="Premarket session (4:00am-9:30am ET)"
        />
      ))}
    </div>
  );
};
