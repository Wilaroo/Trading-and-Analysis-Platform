/**
 * RegimeFocusPanel — v322 Regime Focus List strip.
 *
 * The top-down funnel's "find the right stocks" output:
 *   Market regime (multi-TF modes) → Sector regime → RS leadership →
 *   ranked LONG focus (RS≥80 leaders in strong/rotating-in sectors) +
 *   SHORT focus (RS≤20 laggards in weak/rotating-out sectors).
 *
 * Data: GET /api/scanner/regime-focus-list (server cache 5 min).
 * Collapsible band under the RegimeStrip. Click a chip → focus symbol.
 */
import React, { useEffect, useState, useCallback } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const REFRESH_MS = 60_000;

const SECTOR_TINT = {
  strong: { fg: '#86efac', bg: 'rgba(34,197,94,0.14)' },
  rotating_in: { fg: '#a7f3d0', bg: 'rgba(16,185,129,0.12)' },
  weak: { fg: '#fda4af', bg: 'rgba(244,63,94,0.14)' },
  rotating_out: { fg: '#fdba74', bg: 'rgba(249,115,22,0.12)' },
};

const Chip = ({ row, side, onSelect }) => {
  const tint = SECTOR_TINT[row.sector_regime] || { fg: '#a1a1aa', bg: 'rgba(113,113,122,0.14)' };
  return (
    <button
      type="button"
      data-testid={`focus-chip-${side}-${row.symbol}`}
      onClick={() => onSelect && onSelect(row.symbol)}
      title={`${row.symbol} · RS ${row.rs_rating} · ${row.sector || '—'} ${row.sector_regime}`}
      className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono-data leading-none transition-colors duration-150 hover:brightness-125"
      style={{ background: tint.bg, color: tint.fg }}
    >
      <span className="font-semibold">{row.symbol}</span>
      <span className="opacity-80">{row.rs_rating}</span>
    </button>
  );
};

export const RegimeFocusPanel = ({ onSelectSymbol }) => {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(true);

  const fetchList = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/scanner/regime-focus-list`);
      if (!res.ok) return;
      const json = await res.json();
      if (json && json.success) setData(json);
    } catch (_e) { /* keep last */ }
  }, []);

  useEffect(() => {
    fetchList();
    const t = setInterval(fetchList, REFRESH_MS);
    return () => clearInterval(t);
  }, [fetchList]);

  const longs = data?.longs || [];
  const shorts = data?.shorts || [];
  if (!data || (longs.length === 0 && shorts.length === 0)) return null;

  return (
    <div
      data-testid="regime-focus-panel"
      className="border-b border-zinc-800 bg-zinc-950/60 px-3 py-1.5 text-xs"
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="regime-focus-toggle"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-zinc-400 hover:text-zinc-200 transition-colors duration-150 uppercase tracking-wider text-[10px] font-semibold"
        >
          <span>{open ? '▾' : '▸'}</span>
          <span>🎯 Regime Focus</span>
        </button>
        <span className="text-zinc-600 text-[10px]">
          {longs.length}L · {shorts.length}S · {data.market_context || 'UNKNOWN'}
        </span>
        {data.modes?.long && (
          <span className="text-emerald-500/80 text-[10px] uppercase">L:{data.modes.long}</span>
        )}
        {data.modes?.short && (
          <span className="text-rose-500/80 text-[10px] uppercase">S:{data.modes.short}</span>
        )}
      </div>
      {open && (
        <div className="mt-1.5 flex flex-col gap-1">
          {longs.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap" data-testid="focus-longs-row">
              <span className="text-emerald-400/90 text-[10px] font-semibold w-12 shrink-0">LONGS</span>
              {longs.slice(0, 24).map((r) => (
                <Chip key={r.symbol} row={r} side="long" onSelect={onSelectSymbol} />
              ))}
            </div>
          )}
          {shorts.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap" data-testid="focus-shorts-row">
              <span className="text-rose-400/90 text-[10px] font-semibold w-12 shrink-0">SHORTS</span>
              {shorts.slice(0, 24).map((r) => (
                <Chip key={r.symbol} row={r} side="short" onSelect={onSelectSymbol} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default RegimeFocusPanel;
