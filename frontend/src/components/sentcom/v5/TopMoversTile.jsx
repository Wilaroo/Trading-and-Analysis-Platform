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
// "Top Movers" was misleading: the tile renders SPY / QQQ / IWM / DIA
// / VIX, which are index + volatility ETFs, not the day's biggest
// movers. Renamed to "Indexes" so the label is honest. If/when we
// wire a real top-mover scanner endpoint (biggest %-movers from the
// active scanner universe), this tile can split into two: an
// `IndexesTile` (this) + a separate `TopMoversTile`.
const DEFAULT_SYMBOLS = ['SPY', 'QQQ', 'IWM', 'DIA', 'VIX'];
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
    const qs = encodeURIComponent(symbols.join(','));
    try {
      const resp = await fetch(
        `${BACKEND_URL}/api/live/briefing-snapshot?symbols=${qs}&bar_size=${encodeURIComponent(barSize)}`
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (!data.success) throw new Error(data.error || 'briefing-snapshot failed');
      const successful = (data.snapshots || []).filter((s) => s.success);
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
          Indexes
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
