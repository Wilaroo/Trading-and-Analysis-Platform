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
  // v19.31.10 — per-column filter chip groups. Each entry: {
  //   key: data column to filter on (e.g. 'direction')
  //   label: human label rendered before the chips
  //   values: 'auto' (extract distinct from rows) | string[]
  //   format: optional fn(v) => label rendered on chip
  //   sort: optional fn(values) => values (pre-sort the chip order)
  //   maxValues: optional cap on chip count (extra → '+N more' chip)
  // }
  filters = [],
}) => {
  const panelRef = useRef(null);
  const [sortKey, setSortKey] = useState(defaultSortKey || (columns[0]?.sortKey ?? columns[0]?.key));
  const [sortDir, setSortDir] = useState(defaultSortDir);
  // Active filters — { [filterKey]: Set(values) }. Empty / missing
  // Set means "no filter applied for this column".
  const [activeFilters, setActiveFilters] = useState({});

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

  // v19.31.10 — auto-extract distinct values for each filter group.
  // Memoized off `rows` so toggling a chip doesn't re-flatten the list.
  const filterGroups = useMemo(() => {
    return (filters || []).map(f => {
      let values;
      if (f.values === 'auto' || !Array.isArray(f.values)) {
        const seen = new Set();
        for (const r of rows) {
          const v = r?.[f.key];
          if (v == null || v === '') continue;
          seen.add(v);
        }
        values = Array.from(seen);
      } else {
        values = [...f.values];
      }
      // Stable sort: alpha for strings, numeric for numbers
      values.sort((a, b) => {
        if (typeof a === 'number' && typeof b === 'number') return a - b;
        return String(a).localeCompare(String(b));
      });
      if (typeof f.sort === 'function') {
        values = f.sort(values);
      }
      const cap = f.maxValues ?? 8;
      const overflow = values.length > cap ? values.length - cap : 0;
      return {
        key: f.key,
        label: f.label || f.key,
        values: values.slice(0, cap),
        overflow,
        format: f.format || ((v) => String(v)),
      };
    });
  }, [rows, filters]);

  // Apply active filters (AND across columns, OR within a column).
  const filteredRows = useMemo(() => {
    const keys = Object.keys(activeFilters).filter(k => activeFilters[k] && activeFilters[k].size > 0);
    if (keys.length === 0) return rows;
    return rows.filter(r => keys.every(k => activeFilters[k].has(r?.[k])));
  }, [rows, activeFilters]);

  const sortedRows = useMemo(() => {
    if (!sortKey) return filteredRows;
    const arr = [...filteredRows];
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
  }, [filteredRows, sortKey, sortDir]);

  const toggleFilter = (groupKey, value) => {
    setActiveFilters(prev => {
      const cur = prev[groupKey] ? new Set(prev[groupKey]) : new Set();
      if (cur.has(value)) cur.delete(value);
      else cur.add(value);
      return { ...prev, [groupKey]: cur };
    });
  };

  const clearAllFilters = () => setActiveFilters({});

  const totalActive = Object.values(activeFilters)
    .reduce((s, v) => s + (v?.size || 0), 0);

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
            {/* v19.31.10 — show filtered/total when a filter is active */}
            {totalActive > 0 && filteredRows.length !== rows.length
              ? `${filteredRows.length}/${rows.length}`
              : rows.length}
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

      {/* v19.31.10 — Filter chips. One row per group; click to toggle.
          Hidden entirely if no filters configured OR no values to show
          (e.g. an empty rows list). */}
      {filterGroups.length > 0 && filterGroups.some(g => g.values.length > 0) && (
        <div
          data-testid={`${testIdPrefix}-filters`}
          className="px-3 py-1.5 border-b border-zinc-800 bg-zinc-950/50"
        >
          {filterGroups.map(g => {
            if (g.values.length === 0) return null;
            const active = activeFilters[g.key] || new Set();
            return (
              <div
                key={g.key}
                data-testid={`${testIdPrefix}-filter-row-${g.key}`}
                className="flex items-center gap-1 flex-wrap py-0.5"
              >
                <span className="text-[10px] uppercase tracking-wider text-zinc-600 mr-1 shrink-0">
                  {g.label}
                </span>
                {g.values.map(v => {
                  const on = active.has(v);
                  return (
                    <button
                      key={String(v)}
                      type="button"
                      data-testid={`${testIdPrefix}-filter-${g.key}-${v}`}
                      onClick={() => toggleFilter(g.key, v)}
                      className={`px-1.5 py-0.5 text-[10px] rounded border transition-colors ${
                        on
                          ? 'bg-zinc-100 text-zinc-950 border-zinc-100'
                          : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:text-zinc-200'
                      }`}
                    >
                      {g.format(v)}
                    </button>
                  );
                })}
                {g.overflow > 0 && (
                  <span className="text-[10px] text-zinc-600 ml-1">+{g.overflow}</span>
                )}
              </div>
            );
          })}
          {totalActive > 0 && (
            <div className="flex items-center justify-end pt-0.5">
              <button
                type="button"
                data-testid={`${testIdPrefix}-filters-clear`}
                onClick={clearAllFilters}
                className="text-[10px] text-zinc-500 hover:text-zinc-200 underline-offset-2 hover:underline"
              >
                clear filters ({totalActive})
              </button>
            </div>
          )}
        </div>
      )}

      {sortedRows.length === 0 ? (
        <div data-testid={`${testIdPrefix}-empty`} className="px-3 py-6 text-center text-[12px] text-zinc-500">
          {totalActive > 0 ? 'No matches for the selected filters.' : emptyText}
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
