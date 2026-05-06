/**
 * TopMoversTile — V5 HUD tile showing biggest movers on the watchlist.
 * Reads /api/live/briefing-snapshot every 30s; ranks by |change_pct|.
 *
 * Clickable symbols pop the EnhancedTickerModal via the onSelectSymbol
 * callback. Failed snapshots are hidden (no point showing noise when the
 * pusher RPC is down — the DataFreshnessBadge / LiveDataChip already
 * signal that condition elsewhere).
 *
 * Watchlist defaults to the five core index / volatility instruments but
 * can be overridden via prop. Refresh cadence is tuned for RTH (~30s
 * matches the Phase 1 live_bar_cache TTL so we don't spam the pusher).
 */

import React, { useEffect, useState, useCallback } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
// ── v19.34.23 (2026-05-06) — Operator pointed out 2026-05-06 that
// "Top Movers" was misleading: the tile previously rendered only
// SPY / QQQ / IWM / DIA / VIX (the index/volatility ETFs hard-coded
// here) and called them "movers." First fix renamed them to "Indexes."
//
// ── v19.34.24 (2026-05-06) — Replaced static index list with a fetch
// against `/api/live/briefing-top-movers` (already exists; ranks the
// dynamic watchlist of positions + scanner top-10 + core indices by
// |change_pct|). We then filter out the core indices client-side so
// the tile shows actual stocks moving the most. Indexes are still
// visible in the briefings strip and the chart-timeline.
const CORE_INDICES = new Set(['SPY', 'QQQ', 'IWM', 'DIA', 'VIX']);
// Backwards-compat: kept for any external callers that still pass a
// `symbols` prop to TopMoversTile (none in-repo as of v19.34.24).
const DEFAULT_SYMBOLS = null;
const REFRESH_MS = 30_000;
const MAX_ROWS = 5;

const formatPct = (v) => {
  if (v == null || Number.isNaN(v)) return '—';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
};

const formatPrice = (v) => {
  if (v == null || Number.isNaN(v)) return '—';
  return `$${Number(v).toFixed(2)}`;
};

export const TopMoversTile = ({
  symbols = DEFAULT_SYMBOLS,
  onSelectSymbol,
  barSize = '5 mins',
  className = '',
}) => {
  const [snapshots, setSnapshots] = useState([]);
  const [marketState, setMarketState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSnapshots = useCallback(async () => {
    try {
      // v19.34.24 — Two paths:
      //   (A) caller passed an explicit `symbols` list → use the static
      //       briefing-snapshot endpoint with that list (preserves the
      //       pre-v19.34.24 contract for any external embed).
      //   (B) default → hit `/api/live/briefing-top-movers` which uses
      //       the dynamic watchlist (positions + scanner top-10 + core
      //       indices) ranked by |change_pct|. We then filter out the
      //       core indices so the tile actually shows movers.
      let url;
      if (symbols && Array.isArray(symbols) && symbols.length) {
        const qs = encodeURIComponent(symbols.join(','));
        url = `${BACKEND_URL}/api/live/briefing-snapshot?symbols=${qs}&bar_size=${encodeURIComponent(barSize)}`;
      } else {
        url = `${BACKEND_URL}/api/live/briefing-top-movers?bar_size=${encodeURIComponent(barSize)}`;
      }
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || 'briefing-top-movers failed');
      let successful = (data.snapshots || []).filter((s) => s.success);
      // v19.34.24 — When pulling from briefing-top-movers, drop the
      // core indices client-side. Server includes them so the
      // MorningBriefing UI can show indices in a separate row; here
      // we want movers only.
      if (!symbols) {
        successful = successful.filter((s) => !CORE_INDICES.has((s.symbol || '').toUpperCase()));
      }
      setSnapshots(successful);
      setMarketState(data.market_state);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [symbols, barSize]);

  useEffect(() => {
    fetchSnapshots();
    const t = setInterval(fetchSnapshots, REFRESH_MS);
    return () => clearInterval(t);
  }, [fetchSnapshots]);

  const rows = snapshots.slice(0, MAX_ROWS);

  return (
    <div
      data-testid="top-movers-tile"
      data-help-id="top-movers-tile"
      className={`v5-panel flex items-center gap-2 px-2 py-0.5 text-[11px] bg-zinc-950 ${className}`}
    >
      <div className="flex items-center gap-1.5 min-w-fit">
        <span className="v5-mono text-[10px] text-zinc-500 uppercase tracking-wide">
          Top Movers
        </span>
        {marketState && (
          <span
            data-testid="top-movers-market-state"
            className="v5-mono text-[10px] text-zinc-600 uppercase"
          >
            · {marketState}
          </span>
        )}
      </div>

      <div className="flex-1 flex items-center gap-2 overflow-x-auto v5-scroll">
        {loading && rows.length === 0 && (
          <span className="v5-mono text-[11px] text-zinc-600">loading…</span>
        )}
        {!loading && rows.length === 0 && !error && (
          <span data-testid="top-movers-empty" className="v5-mono text-[11px] text-zinc-600">
            no live data (pusher offline or pre-trade)
          </span>
        )}
        {error && (
          <span data-testid="top-movers-error" className="v5-mono text-[11px] text-rose-500">
            {error}
          </span>
        )}
        {rows.map((snap) => {
          const up = (snap.change_pct || 0) >= 0;
          return (
            <button
              type="button"
              key={snap.symbol}
              data-testid={`top-movers-symbol-${snap.symbol}`}
              onClick={() => onSelectSymbol?.(snap.symbol)}
              className="flex items-center gap-1 hover:bg-zinc-900 rounded px-1 py-0 transition-colors cursor-pointer"
            >
              <span className="v5-mono font-bold text-zinc-100">{snap.symbol}</span>
              <span className="v5-mono text-zinc-400">{formatPrice(snap.latest_price)}</span>
              <span
                className={`v5-mono font-bold ${up ? 'v5-up text-emerald-400' : 'v5-down text-rose-400'}`}
              >
                {formatPct(snap.change_pct)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default TopMoversTile;
