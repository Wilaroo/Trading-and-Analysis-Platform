/**
 * V5 OpenPositions — compact positions panel matching the mockup's middle-
 * right segment. One row per open position with symbol, side chip, live PnL,
 * sparkline, and thin "why" line showing SL/PT + model confidence.
 */
import React from 'react';
import { LiveDataChip } from './LiveDataChip';

const formatR = (r) => {
  if (r == null || Number.isNaN(Number(r))) return '';
  const n = Number(r);
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}R`;
};

const formatUsd = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '';
  const n = Number(v);
  return `${n >= 0 ? '+$' : '−$'}${Math.abs(n).toFixed(0)}`;
};


const PositionRow = ({ position, onClick }) => {
  const dir = (position.direction || position.side || '').toLowerCase();
  const side = dir === 'short' ? 'SHORT' : 'LONG';
  const setup = position.setup_type || position.strategy || '';
  const pnlUsd = position.unrealized_pnl ?? position.pnl ?? 0;
  const pnlR = position.pnl_r ?? position.r_multiple ?? position.unrealized_r;
  const chipClass = dir === 'short' ? 'v5-chip-veto' : 'v5-chip-manage';
  const pnlColor = Number(pnlUsd) >= 0 ? 'v5-up' : 'v5-down';
  const sparkColor = Number(pnlUsd) >= 0 ? '#22c55e' : '#ef4444';

  // Synthesize a simple upward / downward sparkline based on PnL sign; if the
  // hook exposes a real series in `position.pnl_series` we use that instead.
  const points = Array.isArray(position.pnl_series) && position.pnl_series.length > 2
    ? position.pnl_series
    : null;

  return (
    <div
      data-testid={`v5-open-position-${position.symbol}`}
      onClick={onClick}
      className="px-3 py-2 border-b border-zinc-900 hover:bg-white/5 cursor-pointer transition-colors"
    >
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="v5-mono font-bold text-sm text-zinc-100 hover:text-cyan-300 hover:underline transition-colors"
            data-testid={`open-position-symbol-${position.symbol}`}
          >
            {position.symbol}
          </span>
          <span className={`v5-chip ${chipClass}`}>{side}{setup ? ` ${setup}` : ''}</span>
        </div>
        <span className={`v5-mono text-xs font-semibold ${pnlColor}`}>
          {formatUsd(pnlUsd)}{pnlR != null ? ` · ${formatR(pnlR)}` : ''}
        </span>
      </div>
      {points && (
        <svg viewBox="0 0 180 24" className="w-full h-6 mt-1">
          <polyline
            points={points.slice(-30).map((v, i) => `${(i / 29) * 180},${24 - ((v - Math.min(...points)) / Math.max(1e-6, (Math.max(...points) - Math.min(...points)))) * 22}`).join(' ')}
            fill="none"
            stroke={sparkColor}
            strokeWidth="1.2"
          />
        </svg>
      )}
      <div className="v5-why-dim mt-1 truncate">
        {position.stop_price != null && <span>SL {Number(position.stop_price).toFixed(2)}</span>}
        {(() => {
          // Backend bot positions provide a `target_prices` array (one per
          // scale-out level). Legacy / IB-only rows may provide a scalar
          // `target_price`. Render the first target in either case.
          const pt = position.target_price
            ?? (Array.isArray(position.target_prices) ? position.target_prices[0] : null);
          return pt != null ? <span> · PT {Number(pt).toFixed(2)}</span> : null;
        })()}
        {position.entry_price != null && <span> · E {Number(position.entry_price).toFixed(2)}</span>}
        {position.p_win != null && (() => {
          // Handle both fraction (0.59) and pre-scaled percentage (59) forms
          const n = Number(position.p_win);
          const pct = Math.abs(n) > 1 ? n : n * 100;
          return <span> · P(win) {Math.round(pct)}%</span>;
        })()}
      </div>
    </div>
  );
};


export const OpenPositionsV5 = ({ positions, totalPnl, loading, onSelectPosition }) => {
  const open = (positions || []).filter(p => p && p.status !== 'closed');

  return (
    <div data-testid="v5-open-positions" data-help-id="open-positions" className="flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <div className="flex items-center gap-2">
          <div className="v5-panel-title">Open ({open.length})</div>
          <LiveDataChip compact />
        </div>
        <div className={`v5-mono text-[12px] ${Number(totalPnl) >= 0 ? 'v5-up' : 'v5-down'}`}>
          {totalPnl != null ? formatUsd(totalPnl) : ''}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto v5-scroll">
        {loading && open.length === 0 && (
          <div className="px-3 py-4 text-[13px] text-zinc-500">Loading positions…</div>
        )}
        {!loading && open.length === 0 && (
          <div className="px-3 py-4 text-[13px] text-zinc-500">No open positions.</div>
        )}
        {open.map(p => (
          <PositionRow key={p.id || p._id || p.symbol} position={p} onClick={() => onSelectPosition?.(p)} />
        ))}
      </div>
    </div>
  );
};

export default OpenPositionsV5;
