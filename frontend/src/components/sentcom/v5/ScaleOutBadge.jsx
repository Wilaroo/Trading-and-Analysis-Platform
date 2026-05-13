/**
 * ScaleOutBadge — compact V5 chip showing scale-out progress on an
 * open position. Only renders when at least one partial exit has
 * fired (no clutter for un-scaled positions).
 *
 * Layout: `T2 · 50%R` — the highest target index hit + percentage of
 * the original position still held. Hover reveals the full per-exit
 * breakdown: target index, shares sold, fill price, partial PnL.
 *
 * 2026-02-13 v19.34.154 (P2 — scale-out tiles)
 */
import React from 'react';
import { Layers } from 'lucide-react';

const fmtUsd = (n) => {
  if (n == null || isNaN(n)) return '—';
  const s = Number(n) >= 0 ? '+' : '−';
  return `${s}$${Math.abs(Number(n)).toFixed(0)}`;
};

const fmtPx = (n) => (n == null || isNaN(n) ? '—' : Number(n).toFixed(2));

export const ScaleOutBadge = ({ position }) => {
  const original = Number(position?.original_shares || 0);
  const remaining = Number(position?.remaining_shares || 0);
  const closed = Math.max(0, original - remaining);
  const exits = Array.isArray(position?.scale_out_config?.partial_exits)
    ? position.scale_out_config.partial_exits
    : [];

  // Render nothing if no scale-out has occurred.
  if (exits.length === 0 || closed === 0 || original === 0) return null;

  const pctRemaining = Math.round((remaining / original) * 100);
  const pctClosed = 100 - pctRemaining;
  const lastTargetIdx = exits[exits.length - 1]?.target_idx;
  const lastLabel = lastTargetIdx != null ? `T${lastTargetIdx}` : `${exits.length}×`;

  // Realised PnL across all partial exits.
  const realisedPnl = exits.reduce(
    (sum, e) => sum + (Number(e.pnl) || 0), 0
  );

  // Color: green if partials were profitable (typical winner), amber otherwise.
  const palette = realisedPnl >= 0
    ? 'bg-emerald-950/40 text-emerald-300 border-emerald-800/60'
    : 'bg-amber-950/40 text-amber-300 border-amber-800/60';

  const tooltipLines = [
    `Original ${original}  ·  Closed ${closed} (${pctClosed}%)  ·  Remaining ${remaining} (${pctRemaining}%)`,
    `Realised partial PnL: ${fmtUsd(realisedPnl)}`,
    '── per-target ──',
    ...exits.map((e) =>
      `T${e.target_idx ?? '?'}: sold ${e.shares_sold ?? '?'} @ $${fmtPx(e.fill_price ?? e.target_price)} · ${fmtUsd(e.pnl)}`
    ),
  ].join('\n');

  return (
    <span
      data-testid={`scale-out-badge-${position.symbol}`}
      className={`px-1.5 py-0 text-[13px] uppercase tracking-wider rounded border font-bold flex items-center gap-1 ${palette}`}
      title={tooltipLines}
    >
      <Layers className="w-2.5 h-2.5" />
      <span data-testid={`scale-out-badge-last-target-${position.symbol}`}>
        {lastLabel}
      </span>
      <span className="opacity-70">·</span>
      <span data-testid={`scale-out-badge-pct-remaining-${position.symbol}`}>
        {pctRemaining}%R
      </span>
    </span>
  );
};

/**
 * ScaleOutDetails — expanded-panel section showing the full
 * original/closed/remaining breakdown and a per-target table.
 * Renders only when a scale-out has actually occurred.
 */
export const ScaleOutDetails = ({ position }) => {
  const original = Number(position?.original_shares || 0);
  const remaining = Number(position?.remaining_shares || 0);
  const closed = Math.max(0, original - remaining);
  const exits = Array.isArray(position?.scale_out_config?.partial_exits)
    ? position.scale_out_config.partial_exits
    : [];

  if (exits.length === 0 || original === 0) return null;

  const pctRemaining = Math.round((remaining / original) * 100);
  const pctClosed = 100 - pctRemaining;
  const realisedPnl = exits.reduce(
    (sum, e) => sum + (Number(e.pnl) || 0), 0
  );

  return (
    <div
      data-testid={`scale-out-details-${position.symbol}`}
      className="px-2 py-1.5 rounded bg-zinc-900/40 border border-zinc-800/60"
    >
      <div className="flex items-center justify-between text-[13px] uppercase tracking-wider text-zinc-500 mb-1">
        <span>Scale-out progress</span>
        <span
          data-testid={`scale-out-details-realised-${position.symbol}`}
          className={realisedPnl >= 0 ? 'text-emerald-300' : 'text-amber-300'}
        >
          realised {fmtUsd(realisedPnl)}
        </span>
      </div>

      {/* 3-up summary: original | closed | remaining */}
      <div className="grid grid-cols-3 gap-2 v5-mono text-[12px] mb-2">
        <div>
          <div className="text-[13px] text-zinc-600 uppercase tracking-wider">Original</div>
          <div className="text-zinc-200" data-testid={`scale-out-original-${position.symbol}`}>
            {original}
          </div>
        </div>
        <div>
          <div className="text-[13px] text-zinc-600 uppercase tracking-wider">Closed</div>
          <div className="text-amber-300" data-testid={`scale-out-closed-${position.symbol}`}>
            {closed} <span className="opacity-60 text-[11px]">({pctClosed}%)</span>
          </div>
        </div>
        <div>
          <div className="text-[13px] text-zinc-600 uppercase tracking-wider">Remaining</div>
          <div className="text-emerald-300" data-testid={`scale-out-remaining-${position.symbol}`}>
            {remaining} <span className="opacity-60 text-[11px]">({pctRemaining}%)</span>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="w-full h-1.5 rounded-full bg-zinc-800/80 overflow-hidden mb-2"
        title={`${pctRemaining}% remaining`}
      >
        <div
          data-testid={`scale-out-bar-${position.symbol}`}
          className="h-full bg-emerald-500/70 transition-[width] duration-300"
          style={{ width: `${pctRemaining}%` }}
        />
      </div>

      {/* Per-target rows */}
      <div className="space-y-0.5">
        {exits.map((e, i) => (
          <div
            key={i}
            className="flex items-center gap-3 text-[12px] v5-mono text-zinc-400"
            data-testid={`scale-out-exit-row-${position.symbol}-${e.target_idx ?? i}`}
          >
            <span className="text-cyan-400 font-bold w-6">T{e.target_idx ?? i + 1}</span>
            <span className="text-zinc-300">{e.shares_sold ?? '—'}sh</span>
            <span className="text-zinc-500">@</span>
            <span className="text-zinc-300">${fmtPx(e.fill_price ?? e.target_price)}</span>
            <span className={`ml-auto ${(Number(e.pnl) || 0) >= 0 ? 'text-emerald-300' : 'text-amber-300'}`}>
              {fmtUsd(e.pnl)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ScaleOutBadge;
