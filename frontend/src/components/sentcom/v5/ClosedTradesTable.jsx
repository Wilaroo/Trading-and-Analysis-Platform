/**
 * ClosedTradesTable — v19.34.177 (portable foundation)
 *
 * Layout-agnostic, presentational rich closed-trades table. Designed to drop
 * into BOTH the upcoming V5 pipeline-feed "Close" tab AND the future V6
 * history view with zero rework — it takes data via props and emits events,
 * holding no fetching/layout assumptions of its own.
 *
 * Data shape per row (from GET /api/sentcom/closed-trades):
 *   { trade_id, symbol, setup_type, unified_grade, direction, shares,
 *     entry_price, exit_price, entry_time, exit_time, hold_label,
 *     realized_pnl, r_multiple, mae_r, mfe_r, close_reason, trade_type,
 *     is_synthetic }
 *
 * Props:
 *   trades        Array
 *   summary       { count, win_rate, net_pnl, sum_r, avg_r, worst_r, best_r }
 *   range         'today' | '7d' | '30d'
 *   onRangeChange (range) => void
 *   onRowClick    (trade) => void   // e.g. open bracket-history drilldown
 *   loading       bool
 */
import React, { useMemo, useState } from 'react';

const RANGES = [
  { key: 'today', label: 'Today' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
];

const gradeTone = (g) => {
  const k = (g || '').toUpperCase();
  if (k === 'A' || k === 'A+') return 'text-emerald-300 border-emerald-700/60 bg-emerald-950/40';
  if (k === 'B+' || k === 'B') return 'text-sky-300 border-sky-800/60 bg-sky-950/40';
  if (k === 'C+' || k === 'C') return 'text-amber-300 border-amber-800/60 bg-amber-950/40';
  if (k === 'D') return 'text-orange-300 border-orange-800/60 bg-orange-950/40';
  if (k === 'F') return 'text-rose-300 border-rose-700/60 bg-rose-950/40';
  return 'text-zinc-400 border-zinc-700 bg-zinc-900/60';
};

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
      timeZone: 'America/New_York',
    });
  } catch { return '—'; }
};
const fmtPrice = (p) => (p == null ? '—' : Number(p).toFixed(2));
const fmtMoney = (v) => {
  if (v == null) return '—';
  const n = Number(v);
  return `${n < 0 ? '−' : '+'}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
};
const fmtR = (r) => (r == null ? '—' : `${Number(r) >= 0 ? '+' : '−'}${Math.abs(Number(r)).toFixed(1)}R`);
const pnlClass = (v) => (Number(v) > 0 ? 'text-emerald-400' : Number(v) < 0 ? 'text-rose-400' : 'text-zinc-400');

const COLS = [
  { key: 'symbol', label: 'Sym', align: 'left', sort: (t) => t.symbol || '' },
  { key: 'setup_type', label: 'Setup', align: 'left', sort: (t) => t.setup_type || '' },
  { key: 'unified_grade', label: 'TQS', align: 'center', sort: (t) => t.unified_grade || '' },
  { key: 'direction', label: 'Dir', align: 'center', sort: (t) => t.direction || '' },
  { key: 'shares', label: 'Sh', align: 'right', sort: (t) => t.shares || 0 },
  { key: 'entry_price', label: 'Entry', align: 'right', sort: (t) => t.entry_price || 0 },
  { key: 'exit_price', label: 'Exit', align: 'right', sort: (t) => t.exit_price || 0 },
  { key: 'entry_time', label: 'In', align: 'right', sort: (t) => t.entry_time || '' },
  { key: 'exit_time', label: 'Out', align: 'right', sort: (t) => t.exit_time || '' },
  { key: 'hold_seconds', label: 'Hold', align: 'right', sort: (t) => t.hold_seconds || 0 },
  { key: 'realized_pnl', label: 'P&L', align: 'right', sort: (t) => t.realized_pnl || 0 },
  { key: 'r_multiple', label: 'R', align: 'right', sort: (t) => (t.r_multiple == null ? -999 : t.r_multiple) },
  { key: 'mae_mfe', label: 'MAE/MFE', align: 'right', sort: (t) => t.mfe_r || 0 },
  { key: 'close_reason', label: 'Reason', align: 'left', sort: (t) => t.close_reason || '' },
  { key: 'trade_type', label: 'Type', align: 'right', sort: (t) => t.trade_type || '' },
];

const ClosedTradesTable = ({
  trades = [], summary = {}, range = 'today',
  onRangeChange, onRowClick, loading = false,
}) => {
  const [sortKey, setSortKey] = useState('exit_time');
  const [sortDir, setSortDir] = useState('desc');

  const sorted = useMemo(() => {
    const col = COLS.find((c) => c.key === sortKey);
    if (!col) return trades;
    const dir = sortDir === 'asc' ? 1 : -1;
    return [...trades].sort((a, b) => {
      const va = col.sort(a); const vb = col.sort(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }, [trades, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(key); setSortDir('desc'); }
  };

  const alignCls = (a) => (a === 'left' ? 'text-left' : a === 'center' ? 'text-center' : 'text-right');

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="closed-trades-table">
      {/* summary + range selector */}
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-zinc-800/70 flex-wrap">
        <div className="flex items-center gap-3 text-[11px] font-mono text-zinc-500 flex-wrap" data-testid="closed-summary">
          <span>Trades <b className="text-zinc-200">{summary.count ?? 0}</b></span>
          <span>WR <b className={pnlClass(summary.win_rate >= 50 ? 1 : 0)}>{summary.win_rate ?? 0}%</b></span>
          <span>Net <b className={pnlClass(summary.net_pnl)}>{fmtMoney(summary.net_pnl)}</b></span>
          <span>Σ <b className="text-zinc-200">{summary.sum_r != null ? `${summary.sum_r >= 0 ? '+' : ''}${summary.sum_r}R` : '—'}</b></span>
          <span>avg <b className="text-zinc-300">{summary.avg_r != null ? `${summary.avg_r >= 0 ? '+' : ''}${summary.avg_r}R` : '—'}</b></span>
          <span>worst <b className="text-rose-400">{summary.worst_r != null ? `${summary.worst_r}R` : '—'}</b></span>
        </div>
        <div className="flex gap-1" data-testid="closed-range-selector">
          {RANGES.map((r) => (
            <button
              key={r.key}
              data-testid={`closed-range-${r.key}`}
              onClick={() => onRangeChange && onRangeChange(r.key)}
              className={`font-mono text-[10px] uppercase tracking-wide rounded px-2.5 py-1 border transition-colors ${
                range === r.key
                  ? 'text-slate-200 border-slate-500 bg-slate-500/20'
                  : 'text-zinc-500 border-zinc-700 bg-zinc-900 hover:text-zinc-300'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* table */}
      <div className="flex-1 overflow-auto min-h-0">
        {loading && trades.length === 0 ? (
          <div className="p-6 text-center text-zinc-600 font-mono text-xs">loading…</div>
        ) : trades.length === 0 ? (
          <div className="p-6 text-center text-zinc-600 font-mono text-xs" data-testid="closed-empty">
            No closed trades in this range.
          </div>
        ) : (
          <table className="w-full border-collapse font-mono text-[11px]">
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th
                    key={c.key}
                    data-testid={`closed-col-${c.key}`}
                    onClick={() => toggleSort(c.key)}
                    className={`sticky top-0 z-10 bg-zinc-950 ${alignCls(c.align)} text-zinc-500 font-medium uppercase tracking-wide text-[9px] px-2 py-2 border-b border-zinc-800 cursor-pointer select-none hover:text-zinc-300 whitespace-nowrap`}
                  >
                    {c.label}{sortKey === c.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((t, i) => (
                <tr
                  key={t.trade_id || i}
                  data-testid={`closed-row-${t.symbol}-${i}`}
                  onClick={() => onRowClick && onRowClick(t)}
                  className="border-b border-zinc-900 hover:bg-zinc-900/60 cursor-pointer"
                >
                  <td className="text-left px-2 py-1.5 text-zinc-100 font-semibold whitespace-nowrap">
                    {t.symbol}
                    {t.is_synthetic && <span className="ml-1 text-[8px] text-amber-500/70" title="reconciler/synthetic close">⟲</span>}
                  </td>
                  <td className="text-left px-2 py-1.5 text-zinc-400 whitespace-nowrap">{t.setup_type || '—'}</td>
                  <td className="text-center px-2 py-1.5">
                    {t.unified_grade
                      ? <span className={`px-1 py-0 text-[9px] uppercase rounded border ${gradeTone(t.unified_grade)}`}>{t.unified_grade}</span>
                      : <span className="text-zinc-600">—</span>}
                  </td>
                  <td className={`text-center px-2 py-1.5 ${(t.direction || '').toLowerCase().startsWith('s') ? 'text-rose-400' : 'text-emerald-400'}`}>
                    {(t.direction || '').toLowerCase().startsWith('s') ? 'S' : 'L'}
                  </td>
                  <td className="text-right px-2 py-1.5 text-zinc-300">{t.shares ?? '—'}</td>
                  <td className="text-right px-2 py-1.5 text-zinc-300">{fmtPrice(t.entry_price)}</td>
                  <td className="text-right px-2 py-1.5 text-zinc-300" title={t.exit_price_derived ? 'derived from realized P&L (external close)' : ''}>
                    {t.exit_price_derived && t.exit_price != null ? '~' : ''}{fmtPrice(t.exit_price)}
                  </td>
                  <td className="text-right px-2 py-1.5 text-zinc-500">{fmtTime(t.entry_time)}</td>
                  <td className="text-right px-2 py-1.5 text-zinc-500">{fmtTime(t.exit_time)}</td>
                  <td className="text-right px-2 py-1.5 text-zinc-400">{t.hold_label || '—'}</td>
                  <td className={`text-right px-2 py-1.5 font-medium ${pnlClass(t.realized_pnl)}`}>{fmtMoney(t.realized_pnl)}</td>
                  <td className={`text-right px-2 py-1.5 ${pnlClass(t.r_multiple)}`} title={t.r_multiple_derived ? 'derived from realized P&L ÷ entry risk' : ''}>
                    {t.r_multiple_derived && t.r_multiple != null ? '~' : ''}{fmtR(t.r_multiple)}
                  </td>
                  <td className="text-right px-2 py-1.5 text-zinc-500">
                    {t.mae_r != null || t.mfe_r != null
                      ? `${t.mae_r != null ? Number(t.mae_r).toFixed(1) : '—'}/${t.mfe_r != null ? '+' + Number(t.mfe_r).toFixed(1) : '—'}`
                      : '—'}
                  </td>
                  <td className="text-left px-2 py-1.5 text-zinc-500 whitespace-nowrap">{t.close_reason || '—'}</td>
                  <td className="text-right px-2 py-1.5 text-zinc-600 uppercase">{t.trade_type || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

export default ClosedTradesTable;
export { ClosedTradesTable };
