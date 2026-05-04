/**
 * PipelineStageDrilldown — v19.31.9 (2026-05-04)
 *
 * Generic dropdown panel anchored under any V5 PipelineHUD tile.
 * Replaces the per-stage one-offs (was: ClosedTodayDrilldown only).
 * Renders a sortable, scrollable table from a column-config + row array.
 *
 * Closes on Esc, click-outside, or explicit close button.
 *
 * Props:
 *   open            (bool)              — show/hide
 *   onClose         (fn)                — fires when user dismisses
 *   anchorRef       (ref)               — ref to the parent tile so
 *                                         click-outside doesn't trigger
 *                                         from the tile itself
 *   title           (string)            — small uppercase label
 *   versionTag      (string)            — small footer tag (e.g. "v19.31.9")
 *   headerExtras    (ReactNode)         — extra summary chips next to title
 *   columns         (Array<{
 *     key, label, align?, width?, render?, sortKey?, format?
 *   }>)
 *   rows            (Array<object>)
 *   defaultSortKey  (string)            — initial sort column
 *   defaultSortDir  ('asc'|'desc')
 *   onRowClick      (fn(row))           — optional row click
 *   emptyText       (string)            — shown when rows.length === 0
 *   widthClass      (string)            — tailwind width override
 *                                         (default w-[640px])
 *   testIdPrefix    (string)            — drives `data-testid` values
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { X, ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';

export const PipelineStageDrilldown = ({
  open,
  onClose,
  anchorRef,
  title = 'Drill-down',
  versionTag = '',
  headerExtras = null,
  columns = [],
  rows = [],
  defaultSortKey,
  defaultSortDir = 'desc',
  onRowClick,
  emptyText = 'No data yet.',
  widthClass = 'w-[640px]',
  testIdPrefix = 'pipeline-drilldown',
  footerHint,
}) => {
  const panelRef = useRef(null);
  const [sortKey, setSortKey] = useState(defaultSortKey || (columns[0]?.sortKey ?? columns[0]?.key));
  const [sortDir, setSortDir] = useState(defaultSortDir);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    const onMouse = (e) => {
      if (
        panelRef.current
        && !panelRef.current.contains(e.target)
        && (!anchorRef?.current || !anchorRef.current.contains(e.target))
      ) {
        onClose?.();
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onMouse, true);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onMouse, true);
    };
  }, [open, onClose, anchorRef]);

  const sortedRows = useMemo(() => {
    if (!sortKey) return rows;
    const arr = [...rows];
    arr.sort((a, b) => {
      const av = a?.[sortKey];
      const bv = b?.[sortKey];
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
  }, [rows, sortKey, sortDir]);

  const handleSort = (col) => {
    const key = col.sortKey ?? col.key;
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
      data-testid={`${testIdPrefix}-panel`}
      className={`absolute right-0 top-full mt-1 z-50 ${widthClass} max-w-[95vw] bg-zinc-950 border border-zinc-800 rounded-md shadow-2xl`}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
        <div className="flex items-baseline gap-3 flex-wrap min-w-0">
          <span className="text-[11px] uppercase tracking-wider font-bold text-slate-300 shrink-0">
            {title}
          </span>
          <span data-testid={`${testIdPrefix}-count`} className="v5-mono text-sm text-zinc-100">
            {rows.length}
          </span>
          {headerExtras}
        </div>
        <button
          type="button"
          data-testid={`${testIdPrefix}-close`}
          onClick={onClose}
          className="text-zinc-500 hover:text-zinc-200 transition-colors shrink-0"
          aria-label="Close drilldown"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {sortedRows.length === 0 ? (
        <div data-testid={`${testIdPrefix}-empty`} className="px-3 py-6 text-center text-[12px] text-zinc-500">
          {emptyText}
        </div>
      ) : (
        <div className="max-h-[320px] overflow-y-auto v5-scroll">
          <table className="w-full text-[11px] v5-mono">
            <thead className="sticky top-0 bg-zinc-950 border-b border-zinc-800">
              <tr>
                {columns.map(col => {
                  const active = sortKey === (col.sortKey ?? col.key);
                  const Icon = active
                    ? (sortDir === 'asc' ? ArrowUp : ArrowDown)
                    : ArrowUpDown;
                  const align = col.align || 'left';
                  return (
                    <th
                      key={col.key}
                      data-testid={`${testIdPrefix}-col-${col.key}`}
                      onClick={() => handleSort(col)}
                      className={`px-2 py-1.5 ${col.width || ''} text-${align} cursor-pointer select-none uppercase tracking-wider text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors`}
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
              {sortedRows.map((row, i) => {
                const rowKey = row.trade_id || row.id || row.alert_id || `${row.symbol}-${i}`;
                return (
                  <tr
                    key={rowKey}
                    data-testid={`${testIdPrefix}-row-${row.symbol || i}`}
                    className={`border-b border-zinc-900 hover:bg-white/5 ${onRowClick ? 'cursor-pointer' : ''}`}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {columns.map(col => {
                      const align = col.align || 'left';
                      const raw = row?.[col.key];
                      const content = col.render
                        ? col.render(raw, row)
                        : (col.format ? col.format(raw) : (raw == null ? '—' : String(raw)));
                      return (
                        <td
                          key={col.key}
                          className={`px-2 py-1 text-${align} ${col.cellClass ? col.cellClass(raw, row) : 'text-zinc-300'}`}
                        >
                          {content}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="px-3 py-1.5 border-t border-zinc-800 text-[10px] text-zinc-600 flex items-center justify-between">
        <span>{footerHint || 'Click row for context · Esc to close'}</span>
        {versionTag && <span className="opacity-70">{versionTag}</span>}
      </div>
    </div>
  );
};

export default PipelineStageDrilldown;
