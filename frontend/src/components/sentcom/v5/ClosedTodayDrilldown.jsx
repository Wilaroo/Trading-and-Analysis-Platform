/**
 * ClosedTodayDrilldown — v19.31.8 (2026-05-04)
 *
 * Drop-down panel anchored under the V5 PipelineHUD's CLOSE TODAY tile.
 * Renders today's closed bot trades as a compact sortable table so the
 * operator can review the day's tape in one click instead of hunting
 * through Trail Explorer.
 *
 * Data source: `closed_today` array from /api/sentcom/positions
 * (added in v19.31.7). Each row carries:
 *   { symbol, direction, shares, entry_price, exit_price, realized_pnl,
 *     r_multiple, executed_at, closed_at, close_reason, setup_type,
 *     trade_id }
 *
 * Pure presentational + local state for sort + open. Closes on:
 *   - Esc key
 *   - click outside the panel
 *   - explicit close-button click
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { X, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

const formatMoney = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
};

const formatR = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}R`;
};

const formatTime = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch {
    return '—';
  }
};

const formatPrice = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return n >= 100
    ? n.toFixed(2)
    : n.toFixed(n < 10 ? 3 : 2);
};

const REASON_HUMAN = {
  target_hit: 'target',
  stop_hit: 'stop',
  trail_stop_hit: 'trail',
  scale_out: 'scale-out',
  manual_close: 'manual',
  eod_close: 'EOD',
  oca_closed_externally_v19_31: 'OCA ext',
  phantom_auto_swept_v19_27: 'phantom',
  daily_loss_limit: 'daily-loss',
  reduce_size: 'reduce',
};

const COLUMNS = [
  { key: 'symbol',       label: 'Sym',      align: 'left',  width: 'w-14' },
  { key: 'direction',    label: 'Dir',      align: 'left',  width: 'w-10' },
  { key: 'shares',       label: 'Sh',       align: 'right', width: 'w-12' },
  { key: 'entry_price',  label: 'Entry',    align: 'right', width: 'w-16' },
  { key: 'exit_price',   label: 'Exit',     align: 'right', width: 'w-16' },
  { key: 'realized_pnl', label: '$',        align: 'right', width: 'w-20' },
  { key: 'r_multiple',   label: 'R',        align: 'right', width: 'w-14' },
  { key: 'close_reason', label: 'Reason',   align: 'left',  width: 'w-20' },
  { key: 'closed_at',    label: 'Time',     align: 'right', width: 'w-14' },
];

export const ClosedTodayDrilldown = ({
  open,
  onClose,
  closedToday = [],
  totalRealized = 0,
  winsToday = 0,
  lossesToday = 0,
  anchorRef,
  onJumpToTrade,
}) => {
  const [sortKey, setSortKey] = useState('closed_at');
  const [sortDir, setSortDir] = useState('desc');
  const panelRef = useRef(null);

  // Close on Esc + click-outside.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    const onClick = (e) => {
      if (
        panelRef.current
        && !panelRef.current.contains(e.target)
        && (!anchorRef?.current || !anchorRef.current.contains(e.target))
      ) {
        onClose?.();
      }
    };
    document.addEventListener('keydown', onKey);
    // Use capture so we beat React's bubbling (avoids re-open race).
    document.addEventListener('mousedown', onClick, true);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick, true);
    };
  }, [open, onClose, anchorRef]);

  const sorted = useMemo(() => {
    const arr = [...(closedToday || [])];
    arr.sort((a, b) => {
      const av = a?.[sortKey];
      const bv = b?.[sortKey];
      // Null-safe — push nulls to bottom regardless of direction.
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const isNum = typeof av === 'number' || typeof bv === 'number';
      const cmp = isNum
        ? Number(av) - Number(bv)
        : String(av).localeCompare(String(bv));
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return arr;
  }, [closedToday, sortKey, sortDir]);

  const winRate = (winsToday + lossesToday) > 0
    ? Math.round((winsToday / (winsToday + lossesToday)) * 100)
    : null;

  const sumR = sorted.reduce((s, r) => s + (Number(r.r_multiple) || 0), 0);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  if (!open) return null;

  return (
    <div
      ref={panelRef}
      data-testid="closed-today-drilldown"
      className="absolute right-0 top-full mt-1 z-50 w-[640px] max-w-[95vw] bg-zinc-950 border border-zinc-800 rounded-md shadow-2xl"
      onClick={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <div className="flex items-baseline gap-3">
          <span className="text-[11px] uppercase tracking-wider font-bold text-slate-300">
            Closed Today
          </span>
          <span data-testid="drilldown-count" className="v5-mono text-sm text-zinc-100">
            {sorted.length}
          </span>
          {winRate != null && (
            <span data-testid="drilldown-winrate" className="v5-mono text-[11px] text-zinc-500">
              WR {winRate}% · {winsToday}W / {lossesToday}L
            </span>
          )}
          <span
            data-testid="drilldown-realized"
            className={`v5-mono text-[11px] ${totalRealized >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
          >
            {formatMoney(totalRealized)}
          </span>
          <span
            data-testid="drilldown-sum-r"
            className={`v5-mono text-[11px] ${sumR >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
          >
            {formatR(sumR)}
          </span>
        </div>
        <button
          type="button"
          data-testid="drilldown-close"
          onClick={onClose}
          className="text-zinc-500 hover:text-zinc-200 transition-colors"
          aria-label="Close drilldown"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Body */}
      {sorted.length === 0 ? (
        <div
          data-testid="drilldown-empty"
          className="px-3 py-6 text-center text-[12px] text-zinc-500"
        >
          No trades closed today yet.
        </div>
      ) : (
        <div className="max-h-[320px] overflow-y-auto v5-scroll">
          <table className="w-full text-[11px] v5-mono">
            <thead className="sticky top-0 bg-zinc-950 border-b border-zinc-800">
              <tr>
                {COLUMNS.map(col => {
                  const active = sortKey === col.key;
                  const Icon = active
                    ? (sortDir === 'asc' ? ArrowUp : ArrowDown)
                    : ArrowUpDown;
                  return (
                    <th
                      key={col.key}
                      data-testid={`drilldown-col-${col.key}`}
                      onClick={() => handleSort(col.key)}
                      className={`px-2 py-1.5 ${col.width} text-${col.align} cursor-pointer select-none uppercase tracking-wider text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors`}
                    >
                      <span className="inline-flex items-center gap-1">
                        {col.label}
                        <Icon className={`w-2.5 h-2.5 ${active ? 'text-zinc-200' : 'text-zinc-700'}`} />
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, i) => {
                const dollars = Number(row.realized_pnl) || 0;
                const r = Number(row.r_multiple) || 0;
                const dirIsShort = (row.direction || '').toLowerCase() === 'short';
                const reasonText = REASON_HUMAN[row.close_reason] || row.close_reason || '—';
                return (
                  <tr
                    key={row.trade_id || `${row.symbol}-${i}`}
                    data-testid={`drilldown-row-${row.symbol}`}
                    className="border-b border-zinc-900 hover:bg-white/5 cursor-pointer"
                    onClick={() => onJumpToTrade?.(row)}
                  >
                    <td className="px-2 py-1 font-bold text-zinc-100">{row.symbol}</td>
                    <td className={`px-2 py-1 ${dirIsShort ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {dirIsShort ? 'S' : 'L'}
                    </td>
                    <td className="px-2 py-1 text-right text-zinc-300">{row.shares ?? '—'}</td>
                    <td className="px-2 py-1 text-right text-zinc-400">{formatPrice(row.entry_price)}</td>
                    <td className="px-2 py-1 text-right text-zinc-400">{formatPrice(row.exit_price)}</td>
                    <td className={`px-2 py-1 text-right font-semibold ${dollars >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {formatMoney(dollars)}
                    </td>
                    <td className={`px-2 py-1 text-right font-semibold ${r >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {formatR(r)}
                    </td>
                    <td className="px-2 py-1 text-zinc-500 truncate" title={row.close_reason || ''}>
                      {reasonText}
                    </td>
                    <td className="px-2 py-1 text-right text-zinc-500">{formatTime(row.closed_at || row.executed_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="px-3 py-1.5 border-t border-zinc-800 text-[10px] text-zinc-600 flex items-center justify-between">
        <span>Click row to focus the symbol · Esc to close</span>
        <span className="opacity-70">v19.31.8</span>
      </div>
    </div>
  );
};

export default ClosedTodayDrilldown;
