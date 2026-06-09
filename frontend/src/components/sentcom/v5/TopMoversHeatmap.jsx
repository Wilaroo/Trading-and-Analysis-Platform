/**
 * TopMoversHeatmap — compact, clickable 1-D heatmap of the live
 * watchlist universe (positions + scanner top-10 + core indices),
 * ranked by |change_pct| and colour-graded green↔red by intensity.
 *
 * Replaces the old text-row TopMoversTile. Stays one row tall and
 * scrolls horizontally so it never eats vertical space in the status
 * strip. Every cell opens the EnhancedTickerModal via onSelectSymbol.
 *
 * Data source: GET /api/live/briefing-top-movers (same feed the old
 * tile used). Symbols that fail to resolve (pre-open / pusher down)
 * are dropped client-side.
 */
import React, { useEffect, useState, useCallback } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const REFRESH_MS = 30_000;

// Map change_pct → background tint + foreground. Clamp at ±3% so a
// single outlier doesn't wash out the whole scale.
const heatColor = (pct) => {
  if (pct == null || Number.isNaN(Number(pct))) return { bg: 'rgba(63,63,70,0.4)', fg: '#a1a1aa' };
  const p = Math.max(-3, Math.min(3, Number(pct)));
  const intensity = Math.min(1, Math.abs(p) / 3);
  if (p >= 0) return { bg: `rgba(34,197,94,${(0.12 + intensity * 0.5).toFixed(3)})`, fg: '#dcfce7' };
  return { bg: `rgba(244,63,94,${(0.12 + intensity * 0.5).toFixed(3)})`, fg: '#fee2e2' };
};

const fmtPrice = (v) => (v == null || Number.isNaN(Number(v)) ? '—' : `$${Number(v).toFixed(2)}`);

export const TopMoversHeatmap = ({ onSelectSymbol, barSize = '5 mins', className = '' }) => {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/api/live/briefing-top-movers?bar_size=${encodeURIComponent(barSize)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (!d.success) throw new Error(d.error || 'briefing-top-movers failed');
      const snaps = (d.snapshots || [])
        .filter((s) => s.success && s.change_pct != null)
        .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct));
      setRows(snaps);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [barSize]);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, REFRESH_MS);
    return () => clearInterval(t);
  }, [fetchData]);

  return (
    <div
      data-testid="top-movers-heatmap"
      className={`flex items-center gap-2 px-2 py-0.5 bg-zinc-950 text-[13px] ${className}`}
    >
      <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide shrink-0">Heatmap</span>
      <div className="flex-1 flex items-center gap-1 overflow-x-auto v5-scroll">
        {loading && rows.length === 0 && (
          <span className="v5-mono text-[12px] text-zinc-600">loading…</span>
        )}
        {!loading && rows.length === 0 && !error && (
          <span data-testid="top-movers-heatmap-empty" className="v5-mono text-[12px] text-zinc-600">
            no live data (pusher offline or pre-trade)
          </span>
        )}
        {error && (
          <span data-testid="top-movers-heatmap-error" className="v5-mono text-[12px] text-rose-500">{error}</span>
        )}
        {rows.map((s) => {
          const c = heatColor(s.change_pct);
          const up = Number(s.change_pct) >= 0;
          return (
            <button
              type="button"
              key={s.symbol}
              data-testid={`heatmap-cell-${s.symbol}`}
              onClick={() => onSelectSymbol?.(s.symbol)}
              title={`${s.symbol} · ${fmtPrice(s.latest_price)} · ${up ? '+' : ''}${Number(s.change_pct).toFixed(2)}%`}
              className="flex flex-col items-center justify-center rounded px-1.5 py-0.5 min-w-[56px] hover:brightness-125 transition cursor-pointer"
              style={{ backgroundColor: c.bg, color: c.fg }}
            >
              <span className="v5-mono font-bold text-[12px] leading-tight">{s.symbol}</span>
              <span className="v5-mono text-[11px] leading-tight">
                {up ? '+' : ''}{Number(s.change_pct).toFixed(1)}%
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default TopMoversHeatmap;
