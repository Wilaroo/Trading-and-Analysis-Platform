#!/usr/bin/env python3
"""
apply_v324.py — Infinite chart history scrolling + timeframe availability
==========================================================================
Operator request (2026-06-12): "i dont want a prior day toggle. i just
want to be able to zoom/scroll and the charts load in realtime previous
days, weeks data." Plus: gray out timeframe buttons (e.g. 1m) for
lower-tier symbols that have no collected history at that bar size.

WHAT CHANGES
------------
backend/routers/sentcom_chart.py
  • NEW `GET /api/sentcom/chart-history` — returns the next OLDER chunk
    of bars strictly before a unix-seconds cursor, with EMA/BB/VWAP
    computed over a ~220-bar warm-up pad so indicator lines stay
    continuous across the seam. Reads ib_historical_data DIRECTLY
    (hybrid get_bars has a staleness fallback that returns the NEWEST
    bars for an empty old window — would poison a prepend).
  • NEW `GET /api/sentcom/chart/available-timeframes` — bar counts per
    timeframe for a symbol, so the UI can gray out empty timeframes.
  • `/chart-tail` default-days probe aligned with the frontend's
    deepened lookbacks (7/14/30/60/365) so tail polls actually hit the
    cache entry the full /chart load wrote.

frontend/src/components/sentcom/panels/ChartPanel.jsx
  • REMOVED the daysLoaded-doubling lazy-load (full-window refetch,
    capped at 365d). Scrolling/zooming near the leftmost bar now calls
    /chart-history and PREPENDS only the older chunk — lightweight-
    charts keeps the viewport anchored to the right edge, so the
    prepend is seamless and unbounded (back to the start of collected
    data).
  • Timeframe buttons gray out (disabled + tooltip) when the symbol has
    <50 collected bars at that bar size; auto-hops to the closest
    available timeframe so the operator never lands on an empty pane.
  • Small "Loading older history…" pill while a chunk is in flight.

Also writes backend/tests/test_v324_chart_history.py.
SAFE TO RUN MULTIPLE TIMES (idempotent — skips chunks already applied).

Run from repo root:  .venv/bin/python /tmp/apply_v324.py
Then: git add -A && git commit -m "v324: infinite chart history scroll + tf availability" && git push
(commit BEFORE restarting — StartTrading.bat does `git checkout -- .`)
"""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

BACKEND_REL = "backend/routers/sentcom_chart.py"
FRONTEND_REL = "frontend/src/components/sentcom/panels/ChartPanel.jsx"

# ─────────────────────────────────────────────────────────────────────
# BACKEND CHUNKS
# ─────────────────────────────────────────────────────────────────────

BE_CHUNKS = [
    (
        "tail_default_days_alignment",
        '''    tf_default_days = {
        "1min": 1, "5min": 5, "15min": 10, "1hour": 30, "1day": 365,
    }
    candidate_days = [
        tf_default_days.get(tf, 5),
        5, 10, 30, 90, 365,
    ]
''',
        '''    # v324 — aligned with the frontend TIMEFRAMES daysBack defaults
    # (7/14/30/60/365) so the tail probe actually finds the cache entry
    # the full /chart load wrote, instead of recomputing a tiny window.
    tf_default_days = {
        "1min": 7, "5min": 14, "15min": 30, "1hour": 60, "1day": 365,
    }
    candidate_days = [
        tf_default_days.get(tf, 5),
        5, 7, 10, 14, 30, 60, 90, 365,
    ]
''',
    ),
    (
        "chart_history_endpoints",
        '''@router.get("/chart-diagnostic")
async def chart_diagnostic(
''',
        '''# ═══════════════════════════════════════════════════════════════════
# v324 (2026-06-13) — Infinite history scrolling + tf availability
# ═══════════════════════════════════════════════════════════════════
#
# `/chart-history` returns the next OLDER chunk of bars strictly before
# a unix-seconds cursor, with indicators computed over a ~220-bar
# warm-up pad so EMA-200/BB lines stay continuous across the seam. The
# V5 ChartPanel calls this when the user scrolls/zooms near the
# leftmost loaded bar and PREPENDS the result — no more full-window
# doubling refetches, no 365-day ceiling.
#
# IMPORTANT: reads `ib_historical_data` DIRECTLY instead of
# hybrid_data_service.get_bars() because get_bars has a staleness
# fallback that returns the NEWEST bars when the requested (old) window
# is empty — which would poison a prepend with duplicate recent bars.

_HISTORY_CHUNK_CAPS = {
    "1min": 1500,   # ≈2 sessions incl. premarket
    "5min": 1500,   # ≈7 sessions
    "15min": 1000,  # ≈20 sessions
    "1hour": 1000,  # ≈3 months
    "1day": 500,    # ≈2 years
}
_HISTORY_WARMUP_BARS = 220  # EMA-200 + BB-20 seed pad

_TF_TO_BARSIZE = {
    "1min": "1 min", "5min": "5 mins", "15min": "15 mins",
    "1hour": "1 hour", "1day": "1 day",
}


@router.get("/chart-history")
async def get_chart_history(
    symbol: str = Query(..., min_length=1, max_length=10),
    timeframe: str = Query("5min"),
    before: int = Query(
        ..., ge=1,
        description=(
            "Unix-seconds cursor. Returns only bars strictly OLDER than "
            "this. Use the response's `next_before` as the cursor for the "
            "following page — it resumes correctly even when a chunk was "
            "entirely weekend/overnight rows."
        ),
    ),
    session: str = Query("rth_plus_premarket"),
    cap: Optional[int] = Query(None, ge=100, le=5000),
) -> Dict[str, Any]:
    """v324 — paginated older-history chunks for infinite chart scroll."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    tf = timeframe.lower()
    if tf not in _SUPPORTED_TFS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported timeframe '{timeframe}'. Supported: {sorted(_SUPPORTED_TFS)}",
        )
    sym = symbol.upper()
    chunk_cap = int(cap or _HISTORY_CHUNK_CAPS.get(tf, 1000))
    bar_size = _TF_TO_BARSIZE[tf]

    before_dt = datetime.fromtimestamp(int(before), tz=timezone.utc)
    # `date` storage convention mirrors hybrid_data_service._get_from_cache:
    # YYYY-MM-DD strings for daily bars, full ISO strings for intraday.
    before_key = before_dt.strftime("%Y-%m-%d") if tf == "1day" else before_dt.isoformat()

    import asyncio as _aio
    coll = _db["ib_historical_data"]
    fetch_n = chunk_cap + _HISTORY_WARMUP_BARS

    def _sync_fetch():
        return list(
            coll.find(
                {"symbol": sym, "bar_size": bar_size, "date": {"$lt": before_key}},
                {"_id": 0},
            ).sort("date", -1).limit(fetch_n)
        )

    docs = await _aio.to_thread(_sync_fetch)
    has_more = len(docs) >= fetch_n
    if not docs:
        return {
            "success": True, "symbol": sym, "timeframe": tf,
            "before": int(before), "bar_count": 0, "bars": [],
            "indicators": {}, "markers": [],
            "has_more": False, "next_before": None, "earliest_time": None,
        }

    # Oldest doc of the RETURNED chunk (docs is newest-first). Rows older
    # than this are the indicator warm-up pad — sliced off the response.
    boundary_ts = _to_utc_seconds(
        docs[min(chunk_cap, len(docs)) - 1].get("date")
    )

    docs.reverse()  # ascending
    normalised: List[Dict[str, Any]] = []
    for b in docs:
        ts = _to_utc_seconds(b.get("date") or b.get("timestamp") or b.get("time"))
        if ts is None or ts >= int(before):
            continue
        try:
            normalised.append({
                "time": ts,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": int(b.get("volume", 0) or 0),
            })
        except (KeyError, ValueError, TypeError):
            continue
    normalised.sort(key=lambda r: r["time"])
    deduped: List[Dict[str, Any]] = []
    for r in normalised:
        if deduped and deduped[-1]["time"] == r["time"]:
            deduped[-1] = r
        else:
            deduped.append(r)
    normalised = deduped

    if boundary_ts is None and normalised:
        boundary_ts = normalised[0]["time"]

    if tf in {"1min", "5min", "15min", "1hour"} and normalised:
        normalised, _ = _sanitize_intraday_bars(normalised)

    # Session filter — same contract as /chart (tags session: pre|rth).
    if tf in {"1min", "5min", "15min", "1hour"} and session != "all":
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        if session == "rth_plus_premarket":
            window_open, window_close = 4 * 60, 16 * 60
        else:  # "rth"
            window_open, window_close = 9 * 60 + 30, 16 * 60
        kept: List[Dict[str, Any]] = []
        for r in normalised:
            dt_et = datetime.fromtimestamp(r["time"], tz=et)
            if dt_et.weekday() >= 5:
                continue
            mod = dt_et.hour * 60 + dt_et.minute
            if not (window_open <= mod < window_close):
                continue
            r["session"] = "pre" if mod < (9 * 60 + 30) else "rth"
            kept.append(r)
        normalised = kept
    else:
        for r in normalised:
            r.setdefault("session", "rth")

    if tf == "1day":
        seen_days = set()
        snapped: List[Dict[str, Any]] = []
        for r in normalised:
            day_ts = (r["time"] // 86400) * 86400
            if day_ts in seen_days:
                continue
            seen_days.add(day_ts)
            r["time"] = day_ts
            snapped.append(r)
        normalised = snapped
        if boundary_ts is not None:
            boundary_ts = (boundary_ts // 86400) * 86400

    if not normalised or boundary_ts is None:
        # Chunk was entirely weekend/overnight rows — hand back the
        # cursor so the client immediately walks to the next older page.
        return {
            "success": True, "symbol": sym, "timeframe": tf,
            "before": int(before), "bar_count": 0, "bars": [],
            "indicators": {}, "markers": [],
            "has_more": has_more, "next_before": boundary_ts,
            "earliest_time": None,
        }

    # Indicators over warm-up + chunk, then slice to the chunk only.
    times = [r["time"] for r in normalised]
    closes = [r["close"] for r in normalised]
    ema_20 = _ema(closes, 20)
    ema_50 = _ema(closes, 50)
    ema_200 = _ema(closes, 200)
    bb_mid, bb_std = _rolling_mean_std(closes, 20)
    bb_upper = [
        (m + 2.0 * s) if (m is not None and s is not None) else None
        for m, s in zip(bb_mid, bb_std)
    ]
    bb_lower = [
        (m - 2.0 * s) if (m is not None and s is not None) else None
        for m, s in zip(bb_mid, bb_std)
    ]
    vwap = _vwap(normalised, per_session=tf != "1day")

    def _slice(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [p for p in series if p["time"] >= boundary_ts]

    chunk = [r for r in normalised if r["time"] >= boundary_ts]
    markers = (
        _fetch_trade_markers(sym, chunk[0]["time"], chunk[-1]["time"])
        if chunk else []
    )

    return {
        "success": True,
        "symbol": sym,
        "timeframe": tf,
        "before": int(before),
        "bar_count": len(chunk),
        "bars": chunk,
        "indicators": {
            "vwap": _slice(_as_series(times, vwap)),
            "ema_20": _slice(_as_series(times, ema_20)),
            "ema_50": _slice(_as_series(times, ema_50)),
            "ema_200": _slice(_as_series(times, ema_200)),
            "bb_upper": _slice(_as_series(times, bb_upper)),
            "bb_middle": _slice(_as_series(times, bb_mid)),
            "bb_lower": _slice(_as_series(times, bb_lower)),
        },
        "markers": markers,
        "has_more": has_more,
        "next_before": boundary_ts,
        "earliest_time": chunk[0]["time"] if chunk else None,
    }


@router.get("/chart/available-timeframes")
async def get_available_timeframes(
    symbol: str = Query(..., min_length=1, max_length=12),
) -> Dict[str, Any]:
    """v324 — bar counts per timeframe for `symbol` from
    ib_historical_data. The V5 ChartPanel grays out timeframe buttons
    with no collected history (Tier 2/3 investment symbols usually only
    carry daily — sometimes hourly — bars)."""
    if _db is None:
        raise HTTPException(status_code=503, detail="db not initialised")
    sym = symbol.upper()
    barsize_to_tf = {v: k for k, v in _TF_TO_BARSIZE.items()}

    import asyncio as _aio

    def _sync_counts():
        return list(_db["ib_historical_data"].aggregate([
            {"$match": {"symbol": sym}},
            {"$group": {"_id": "$bar_size", "n": {"$sum": 1}}},
        ]))

    try:
        rows = await _aio.to_thread(_sync_counts)
    except Exception as exc:  # pragma: no cover
        logger.warning("available-timeframes failed for %s: %s", sym, exc)
        return {"success": False, "symbol": sym, "available": {}, "error": str(exc)}

    available: Dict[str, int] = {}
    for r in rows:
        tf_val = barsize_to_tf.get(r.get("_id"))
        if tf_val:
            available[tf_val] = int(r.get("n", 0) or 0)
    return {"success": True, "symbol": sym, "available": available}


@router.get("/chart-diagnostic")
async def chart_diagnostic(
''',
    ),
]

# ─────────────────────────────────────────────────────────────────────
# FRONTEND CHUNKS
# ─────────────────────────────────────────────────────────────────────

FE_CHUNKS = [
    (
        "state_block",
        '''  // How many days of history are currently loaded. Starts at the timeframe
  // default and grows when the user scrolls/zooms past the leftmost bar so
  // older context is fetched on demand (lazy-load).
  const [daysLoaded, setDaysLoaded] = useState(null);
  // Internal flag: true while a backfill (older-history) fetch is in flight.
  // Prevents duplicate fetches when the user keeps scrolling left.
  const backfillInFlightRef = useRef(false);
  // Hard ceiling on how far back we will lazy-load (matches backend cap).
  const MAX_DAYS_BACK = 365;
''',
        '''  // v324 — true infinite history scrolling. The old mechanism doubled a
  // days-loaded window (capped at 365d) and re-fetched the ENTIRE chart
  // each time the user neared the left edge. Replaced by /chart-history
  // pagination: scroll left → fetch ONLY the next older chunk (keyed by a
  // unix-seconds cursor) → PREPEND. lightweight-charts keeps the viewport
  // anchored relative to the right edge, so the prepend is seamless and
  // unbounded (back to the start of collected data).
  // Internal flag: true while an older-history fetch is in flight.
  const backfillInFlightRef = useRef(false);
  // Whether the backend says more (older) history exists for this
  // (symbol, timeframe). Reset on symbol/timeframe change.
  const hasMoreHistoryRef = useRef(true);
  // Cursor for the next older-history page. null → derive from the
  // earliest loaded bar. The backend returns `next_before` (oldest RAW
  // row it inspected) so weekend-only chunks can't stall pagination.
  const historyCursorRef = useRef(null);
  // Visible pill while an older-history chunk is loading.
  const [historyLoading, setHistoryLoading] = useState(false);
  // v324 — per-symbol timeframe availability ({ tfValue: barCount }).
  // null = unknown → all timeframes enabled. Lower-tier symbols without
  // collected 1m/5m history get those buttons grayed out.
  const [availableTfs, setAvailableTfs] = useState(null);
''',
    ),
    (
        "reset_effects",
        '''  // Reset the lazy-load window whenever the timeframe changes — each
  // timeframe has its own sensible default. Also reset the "fit" flag so
  // the new dataset gets framed once before lazy-loading takes over.
  useEffect(() => {
    setDaysLoaded(active.daysBack);
    hasFittedRef.current = false;
  }, [active.daysBack]);

  // Reset the fit flag when the symbol changes too — otherwise switching
  // symbols would inherit the previous symbol's pan position.
  useEffect(() => { hasFittedRef.current = false; }, [symbol]);
''',
        '''  // v324 — reset history pagination whenever the timeframe changes. Also
  // reset the "fit" flag so the new dataset gets framed once before
  // infinite-scroll takes over.
  useEffect(() => {
    hasMoreHistoryRef.current = true;
    historyCursorRef.current = null;
    hasFittedRef.current = false;
  }, [active.daysBack, active.value]);

  // Reset the fit flag + history cursor when the symbol changes too —
  // otherwise switching symbols would inherit the previous symbol's pan
  // position and pagination cursor.
  useEffect(() => {
    hasFittedRef.current = false;
    hasMoreHistoryRef.current = true;
    historyCursorRef.current = null;
  }, [symbol]);
''',
    ),
    (
        "cache_key",
        '''  const cacheKey = useMemo(
    () => `${symbol || ''}|${active.value}|${daysLoaded || active.daysBack}`,
    [symbol, active, daysLoaded],
  );
''',
        '''  const cacheKey = useMemo(
    () => `${symbol || ''}|${active.value}`,
    [symbol, active],
  );
''',
    ),
    (
        "fetchbars_days",
        '''  // Fetch bars for current symbol + timeframe. Honours the lazy-loaded
  // `daysLoaded` window so subsequent refetches keep older bars on screen.
  // Important: only show the spinner on COLD loads (no cached data) so
  // hot-path refetches don't blank the chart.
  const fetchBars = useCallback(async () => {
    if (!symbol) return;
    const days = daysLoaded || active.daysBack;
''',
        '''  // Fetch bars for current symbol + timeframe (initial window only —
  // older history streams in via /chart-history as the user scrolls).
  // Important: only show the spinner on COLD loads (no cached data) so
  // hot-path refetches don't blank the chart.
  const fetchBars = useCallback(async () => {
    if (!symbol) return;
    const days = active.daysBack;
''',
    ),
    (
        "fetchbars_finally",
        '''    } finally {
      setLoading(false);
      backfillInFlightRef.current = false;
    }
  }, [symbol, active, daysLoaded, cacheKey]);
''',
        '''    } finally {
      setLoading(false);
    }
  }, [symbol, active, cacheKey]);
''',
    ),
    (
        "infinite_history_system",
        '''  // Lazy-load older history when user scrolls/pans/zooms past the leftmost
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
''',
        '''  // ── v324: infinite history scrolling ────────────────────────────────
  // Fetch the next OLDER chunk via /chart-history and PREPEND it. The
  // viewport stays anchored relative to the right edge in lightweight-
  // charts, so the prepend never yanks the user's pan/zoom position.
  // `depth` guards the rare recursion when a chunk was entirely
  // weekend/overnight rows (bars empty but has_more=true).
  const fetchOlderHistory = useCallback(async (depth = 0) => {
    if (!symbol || depth > 3) return;
    if (!hasMoreHistoryRef.current) return;
    const cursor = historyCursorRef.current
      ?? (bars.length > 0 ? Number(bars[0]?.time) : null);
    if (!cursor || !Number.isFinite(cursor)) return;
    if (depth === 0) {
      if (backfillInFlightRef.current) return;
      backfillInFlightRef.current = true;
      setHistoryLoading(true);
    }
    try {
      const resp = await safeGet(
        `/api/sentcom/chart-history?symbol=${encodeURIComponent(symbol)}` +
        `&timeframe=${encodeURIComponent(active.value)}&before=${cursor}`
      );
      if (!resp || resp.success === false) return;
      hasMoreHistoryRef.current = !!resp.has_more;
      if (Number.isFinite(Number(resp.next_before)) && Number(resp.next_before) > 0) {
        historyCursorRef.current = Number(resp.next_before);
      }
      const older = Array.isArray(resp.bars) ? resp.bars : [];
      if (older.length === 0) {
        // Chunk was all weekend/overnight rows — keep walking back.
        if (resp.has_more) await fetchOlderHistory(depth + 1);
        return;
      }
      setBars(prev => {
        const prevEarliest = prev.length > 0 ? Number(prev[0].time) : Infinity;
        const prepend = older.filter(b => Number(b.time) < prevEarliest);
        return prepend.length > 0 ? [...prepend, ...prev] : prev;
      });
      if (resp.indicators && typeof resp.indicators === 'object') {
        setIndicators(prev => {
          const next = { ...prev };
          for (const [key, points] of Object.entries(resp.indicators)) {
            if (!Array.isArray(points) || points.length === 0) continue;
            const existing = Array.isArray(next[key]) ? next[key] : [];
            const existingTimes = new Set(existing.map(p => Number(p.time)));
            next[key] = [
              ...points.filter(p => !existingTimes.has(Number(p.time))),
              ...existing,
            ];
          }
          return next;
        });
      }
      if (Array.isArray(resp.markers) && resp.markers.length > 0) {
        setMarkers(prev => {
          const have = new Set(prev.map(m => `${m.time}|${m.text || ''}`));
          return [
            ...resp.markers.filter(m => !have.has(`${m.time}|${m.text || ''}`)),
            ...prev,
          ];
        });
      }
    } catch (_) {
      /* transient — the next scroll event retries */
    } finally {
      if (depth === 0) {
        backfillInFlightRef.current = false;
        setHistoryLoading(false);
      }
    }
  }, [symbol, active, bars]);

  // Trigger: lightweight-charts `subscribeVisibleLogicalRangeChange`
  // fires on every pan + scroll-wheel zoom. When the visible logical
  // range's `from` index comes within 10 bars of the leftmost loaded bar
  // (or past it), fetch the next older chunk.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return undefined;

    const handleRangeChange = (range) => {
      if (!range) return;
      if (backfillInFlightRef.current || loading) return;
      if (!hasMoreHistoryRef.current) return;
      if (range.from > 10) return;
      fetchOlderHistory();
    };

    try {
      chart.timeScale().subscribeVisibleLogicalRangeChange(handleRangeChange);
    } catch (_) { /* noop */ }
    return () => {
      try {
        chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleRangeChange);
      } catch (_) { /* noop */ }
    };
  }, [fetchOlderHistory, loading]);

  // v324 — per-symbol timeframe availability. Lower-tier symbols may only
  // carry daily (or daily+hourly) history; gray out timeframes with no
  // collected bars so the operator never clicks into an empty pane.
  useEffect(() => {
    let cancelled = false;
    const fetchAvailability = async () => {
      if (!symbol) return;
      try {
        const resp = await safeGet(
          `/api/sentcom/chart/available-timeframes?symbol=${encodeURIComponent(symbol)}`,
          { timeout: 6000 },
        );
        if (!cancelled) setAvailableTfs(resp?.success ? (resp.available || null) : null);
      } catch (_) {
        if (!cancelled) setAvailableTfs(null); // unknown → leave all enabled
      }
    };
    fetchAvailability();
    return () => { cancelled = true; };
  }, [symbol]);

  const MIN_BARS_FOR_TF = 50;
  const isTfAvailable = useCallback((tfValue) => {
    if (!availableTfs) return true; // unknown → don't gray anything out
    return Number(availableTfs[tfValue] || 0) >= MIN_BARS_FOR_TF;
  }, [availableTfs]);

  // Auto-hop to the closest available timeframe when the active one has
  // no data for this symbol (e.g. moving from a Tier-1 scalp symbol on
  // 1m to an investment-tier symbol that only carries daily bars).
  useEffect(() => {
    const cur = TIMEFRAMES.find(t => t.label === timeframe);
    if (!cur || isTfAvailable(cur.value)) return;
    const fallback = ['1d', '1h', '15m', '5m', '1m']
      .map(lbl => TIMEFRAMES.find(t => t.label === lbl))
      .find(t => t && isTfAvailable(t.value));
    if (fallback && fallback.label !== timeframe) setTimeframe(fallback.label);
  }, [timeframe, isTfAvailable]);
''',
    ),
    (
        "timeframe_buttons",
        '''            {TIMEFRAMES.map((t) => (
              <button
                key={t.label}
                data-testid={`chart-timeframe-${t.label}`}
                onClick={() => setTimeframe(t.label)}
                className={`px-2.5 py-0.5 text-[13px] rounded-md transition-colors ${
                  t.label === timeframe
                    ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-400/30'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/5'
                }`}
              >
                {t.label}
              </button>
            ))}
''',
        '''            {TIMEFRAMES.map((t) => {
              // v324 — gray out timeframes with no collected history for
              // this symbol (Tier 2/3 symbols usually lack 1m/5m bars).
              const available = isTfAvailable(t.value);
              return (
                <button
                  key={t.label}
                  data-testid={`chart-timeframe-${t.label}`}
                  onClick={() => available && setTimeframe(t.label)}
                  disabled={!available}
                  title={available
                    ? undefined
                    : `No ${t.label} history collected for ${symbol} — lower-tier symbols only carry coarser bars`}
                  className={`px-2.5 py-0.5 text-[13px] rounded-md transition-colors ${
                    !available
                      ? 'text-zinc-700 opacity-40 cursor-not-allowed'
                      : t.label === timeframe
                      ? 'bg-cyan-500/20 text-cyan-300 ring-1 ring-cyan-400/30'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/5'
                  }`}
                >
                  {t.label}
                </button>
              );
            })}
''',
    ),
    (
        "history_loading_pill",
        '''      {loading && !bars.length && (
        <div
          data-testid="chart-loading"
          className="absolute inset-0 flex items-center justify-center bg-black/20"
        >
          <span className="text-xs text-zinc-400">Loading bars...</span>
        </div>
      )}
''',
        '''      {loading && !bars.length && (
        <div
          data-testid="chart-loading"
          className="absolute inset-0 flex items-center justify-center bg-black/20"
        >
          <span className="text-xs text-zinc-400">Loading bars...</span>
        </div>
      )}
      {/* v324 — older-history chunk in flight (infinite scroll-back) */}
      {historyLoading && (
        <div
          data-testid="chart-history-loading"
          className="absolute top-12 left-3 z-20 flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-cyan-500/40 bg-cyan-950/80 text-[11px] text-cyan-300"
        >
          <RefreshCw className="w-3 h-3 animate-spin" />
          Loading older history…
        </div>
      )}
''',
    ),
]

# ─────────────────────────────────────────────────────────────────────
# Test file
# ─────────────────────────────────────────────────────────────────────

TEST_REL = Path("backend") / "tests" / "test_v324_chart_history.py"

TEST_CONTENT = '''"""v324 — infinite chart history scrolling + timeframe availability.

Static assertions that both halves of the patch are present and the
backend router still compiles. The /chart-history endpoint itself needs
the DGX Mongo (ib_historical_data) to return rows — covered by the
operator's manual curl after restart.
"""
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


def test_chart_history_endpoint_present():
    assert '@router.get("/chart-history")' in BE
    assert "_HISTORY_WARMUP_BARS" in BE
    assert "next_before" in BE
    # Must NOT route through get_bars (staleness fallback poisons prepends)
    history_section = BE.split('@router.get("/chart-history")')[1].split("@router.get")[0]
    assert "get_bars(" not in history_section


def test_available_timeframes_endpoint_present():
    assert '@router.get("/chart/available-timeframes")' in BE


def test_tail_default_days_aligned():
    assert '"1min": 7, "5min": 14, "15min": 30, "1hour": 60, "1day": 365' in BE


def test_frontend_days_doubling_removed():
    assert "daysLoaded" not in FE
    assert "MAX_DAYS_BACK" not in FE


def test_frontend_infinite_scroll_present():
    assert "fetchOlderHistory" in FE
    assert "chart-history?symbol=" in FE
    assert "hasMoreHistoryRef" in FE
    assert "historyCursorRef" in FE


def test_frontend_tf_availability_present():
    assert "available-timeframes" in FE
    assert "isTfAvailable" in FE
    assert "chart-history-loading" in FE
'''


# ─────────────────────────────────────────────────────────────────────
# Applier
# ─────────────────────────────────────────────────────────────────────

def _find_repo_root() -> Path:
    for cand in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (cand / BACKEND_REL).exists() and (cand / FRONTEND_REL).exists():
            return cand
    print("FATAL: run from repo root (backend/ + frontend/ not found)")
    sys.exit(1)


def _apply(path: Path, chunks) -> bool:
    text = path.read_text()
    changed = False
    for name, old, new in chunks:
        if new in text:
            print(f"  [SKIP] {name} — already applied")
            continue
        if old not in text:
            print(f"  [FAIL] {name} — anchor not found in {path.name}.")
            print("         File has drifted from the expected baseline. ABORTING (no partial writes).")
            sys.exit(2)
        if text.count(old) != 1:
            print(f"  [FAIL] {name} — anchor not unique ({text.count(old)} matches). ABORTING.")
            sys.exit(2)
        text = text.replace(old, new, 1)
        changed = True
        print(f"  [OK]   {name}")
    if changed:
        path.write_text(text)
    return changed


def main() -> None:
    root = _find_repo_root()
    print(f"repo root: {root}\n")

    be_path = root / BACKEND_REL
    fe_path = root / FRONTEND_REL

    print(f"── {BACKEND_REL}")
    _apply(be_path, BE_CHUNKS)
    print(f"\n── {FRONTEND_REL}")
    _apply(fe_path, FE_CHUNKS)

    # Compile gate on the backend file.
    try:
        py_compile.compile(str(be_path), doraise=True)
        print("\n[OK]   backend py_compile passed")
    except py_compile.PyCompileError as exc:
        print(f"\n[FAIL] backend py_compile FAILED: {exc}")
        sys.exit(3)

    # Frontend sanity: the chunks we removed must be gone.
    fe_text = fe_path.read_text()
    for forbidden in ("daysLoaded", "MAX_DAYS_BACK"):
        if forbidden in fe_text:
            print(f"[FAIL] frontend still references {forbidden} — manual review needed")
            sys.exit(3)
    print("[OK]   frontend daysLoaded/MAX_DAYS_BACK fully removed")

    test_path = root / TEST_REL
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST_CONTENT)
    print(f"[OK]   wrote {TEST_REL}")

    print("""
v324 APPLIED.

Next steps:
  1. (optional) .venv/bin/python -m pytest backend/tests/test_v324_chart_history.py -q
  2. git add -A && git commit -m "v324: infinite chart history scroll + tf availability" && git push
  3. Restart the app (StartTrading.bat) — commit FIRST (it runs `git checkout -- .`)
  4. Verify:  open any chart, scroll/zoom left — older days/weeks stream in
              with a small cyan "Loading older history…" pill. Timeframes with
              no collected bars for the symbol render grayed out.
     curl 'http://127.0.0.1:8001/api/sentcom/chart/available-timeframes?symbol=SPY'
     curl 'http://127.0.0.1:8001/api/sentcom/chart-history?symbol=SPY&timeframe=5min&before='$(date +%s) | head -c 400
""")


if __name__ == "__main__":
    main()
