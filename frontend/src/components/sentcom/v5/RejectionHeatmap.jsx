/**
 * RejectionHeatmap — v19.34.12 (2026-05-06)
 *
 * Diagnostics → "Rejections" sub-tab. Renders a (Symbol × Setup) grid
 * colored by rejection_count, with tooltips broken down by reason.
 *
 * Surfaces blind-spot patterns like "ORB on XLU always trips
 * max_position_pct" — the kind of signal that gets lost in raw logs.
 *
 * Backend: GET /api/trading-bot/rejection-events?days=7
 */
import React, { useEffect, useMemo, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const heatColor = (count, max) => {
  if (!count || count === 0) return 'bg-zinc-900 text-zinc-700 border-zinc-800';
  const ratio = max > 0 ? count / max : 0;
  if (ratio < 0.2)   return 'bg-amber-950/30 text-amber-300 border-amber-900/60';
  if (ratio < 0.45)  return 'bg-amber-900/40 text-amber-200 border-amber-800/70';
  if (ratio < 0.7)   return 'bg-orange-900/50 text-orange-200 border-orange-800';
  return                  'bg-rose-900/60 text-rose-100 border-rose-700';
};

const fmtTime = (iso) => {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('en-US', { hour12: false }); }
  catch { return iso; }
};

const ReasonTooltip = ({ byReason }) => {
  const entries = Object.entries(byReason || {})
    .sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return null;
  return (
    <div className="absolute z-50 left-full top-0 ml-1 px-2 py-1.5 bg-zinc-900 border border-zinc-700 rounded shadow-lg min-w-[180px]">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">
        Reasons
      </div>
      {entries.map(([reason, count]) => (
        <div key={reason} className="flex justify-between gap-3 text-[11px]">
          <span className="text-zinc-300 truncate">{reason}</span>
          <span className="text-zinc-200 font-semibold v5-mono">{count}</span>
        </div>
      ))}
    </div>
  );
};

const Cell = ({ row }) => {
  const [hover, setHover] = useState(false);
  const max = row?.__max || 1;
  const cls = heatColor(row.total_rejections, max);
  return (
    <td
      className="relative p-0.5"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      data-testid={`rejection-cell-${row.symbol}-${row.setup_type}`}
    >
      <div
        className={`px-2 py-1 rounded border text-[11px] v5-mono cursor-default ${cls}`}
      >
        {row.total_rejections}
      </div>
      {hover && <ReasonTooltip byReason={row.by_reason} />}
    </td>
  );
};

export default function RejectionHeatmap() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(7);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          `${BACKEND_URL}/api/trading-bot/rejection-events?days=${days}&limit=2000`,
        );
        const json = await res.json();
        if (cancelled) return;
        if (json.success) setData(json);
        else setError(json.error || 'fetch_failed');
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const t = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, [days]);

  const grid = useMemo(() => {
    if (!data?.heatmap) return null;
    const { rows = [], symbols = [], setups = [], max_rejections = 0 } = data.heatmap;
    // Build a (symbol → setup → row) lookup for fast cell render.
    const lookup = {};
    for (const r of rows) {
      lookup[r.symbol] = lookup[r.symbol] || {};
      lookup[r.symbol][r.setup_type] = { ...r, __max: max_rejections };
    }
    return { lookup, symbols, setups, max_rejections };
  }, [data]);

  return (
    <div className="p-4 space-y-3" data-testid="diagnostics-rejection-heatmap">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm uppercase tracking-wider text-zinc-300">
            Rejection Heatmap
          </h2>
          <span className="text-[10px] text-zinc-600 v5-mono">v19.34.12</span>
          {loading && <span className="text-[11px] text-zinc-500 italic">refreshing…</span>}
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          <label className="text-zinc-500" htmlFor="rh-days">days</label>
          <select
            id="rh-days"
            data-testid="rejection-heatmap-days"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1"
          >
            <option value={1}>1</option>
            <option value={3}>3</option>
            <option value={7}>7</option>
            <option value={14}>14</option>
          </select>
          <button
            type="button"
            data-testid="rejection-heatmap-toggle-table"
            className="px-2 py-1 rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200"
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? 'Grid' : 'Raw events'}
          </button>
        </div>
      </div>

      {error && (
        <div
          className="px-3 py-2 rounded border border-rose-800 bg-rose-950/40 text-rose-200 text-[11px]"
          data-testid="rejection-heatmap-error"
        >
          {error}
        </div>
      )}

      {data && (
        <div
          className="text-[11px] text-zinc-500 v5-mono flex flex-wrap gap-3"
          data-testid="rejection-heatmap-summary"
        >
          <span>{data.heatmap?.total_events ?? 0} events</span>
          <span>· {data.heatmap?.symbols?.length ?? 0} symbols</span>
          <span>· {data.heatmap?.setups?.length ?? 0} setups</span>
          <span>· peak {data.heatmap?.max_rejections ?? 0}/cell</span>
          {Array.isArray(data.heatmap?.top_reasons) && data.heatmap.top_reasons.length > 0 && (
            <span className="text-zinc-400">
              top: {data.heatmap.top_reasons.slice(0, 3).map((r) => `${r.reason}×${r.count}`).join(', ')}
            </span>
          )}
        </div>
      )}

      {!showTable && grid && grid.symbols.length === 0 && (
        <div className="px-4 py-8 text-center text-zinc-500 text-[12px]" data-testid="rejection-heatmap-empty">
          No structural rejections in the last {days} day{days === 1 ? '' : 's'}. ✓
        </div>
      )}

      {!showTable && grid && grid.symbols.length > 0 && (
        <div className="overflow-auto border border-zinc-800 rounded">
          <table className="text-[11px] border-collapse" data-testid="rejection-heatmap-grid">
            <thead className="sticky top-0 bg-zinc-900 z-10">
              <tr>
                <th className="text-left px-2 py-1 text-zinc-500 uppercase tracking-wider text-[10px] border-b border-zinc-800">
                  symbol \ setup
                </th>
                {grid.setups.map((s) => (
                  <th
                    key={s}
                    className="px-2 py-1 text-zinc-400 v5-mono text-[10px] border-b border-zinc-800 whitespace-nowrap"
                    data-testid={`rejection-col-${s}`}
                  >
                    {s}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.symbols.map((sym) => (
                <tr key={sym} data-testid={`rejection-row-${sym}`}>
                  <td className="text-left px-2 py-1 text-zinc-300 font-semibold border-b border-zinc-900 sticky left-0 bg-zinc-950">
                    {sym}
                  </td>
                  {grid.setups.map((stp) => {
                    const row = grid.lookup[sym]?.[stp];
                    if (!row) {
                      return (
                        <td key={stp} className="p-0.5">
                          <div className="px-2 py-1 rounded border border-zinc-900 text-zinc-800 text-[11px] v5-mono">
                            —
                          </div>
                        </td>
                      );
                    }
                    return <Cell key={stp} row={row} />;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showTable && (
        <div className="overflow-auto border border-zinc-800 rounded">
          <table className="text-[11px] w-full" data-testid="rejection-heatmap-events-table">
            <thead className="sticky top-0 bg-zinc-900 z-10">
              <tr className="text-left text-zinc-500 uppercase tracking-wider text-[10px]">
                <th className="px-2 py-1">When</th>
                <th className="px-2 py-1">Symbol</th>
                <th className="px-2 py-1">Setup</th>
                <th className="px-2 py-1">Reason</th>
                <th className="px-2 py-1 text-right">Count</th>
                <th className="px-2 py-1">Extended</th>
              </tr>
            </thead>
            <tbody>
              {(data?.events || []).map((ev, i) => (
                <tr key={i} className="border-t border-zinc-800/50 v5-mono">
                  <td className="px-2 py-1 text-zinc-400">{fmtTime(ev.created_at_iso || ev.created_at)}</td>
                  <td className="px-2 py-1 text-zinc-200 font-semibold">{ev.symbol}</td>
                  <td className="px-2 py-1 text-zinc-300">{ev.setup_type}</td>
                  <td className="px-2 py-1 text-zinc-300">{ev.reason}</td>
                  <td className="px-2 py-1 text-right text-zinc-200">{ev.rejection_count}</td>
                  <td className="px-2 py-1 text-zinc-400">{ev.extended ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
