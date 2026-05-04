/**
 * TradeTypeChip — v19.31.13 (2026-05-04)
 *
 * Small inline chip showing the origin mode of a trade row.
 * Used in OpenPositionsV5, ClosedTodayDrilldown, Day Tape, and
 * Trade Forensics so the operator can never confuse a paper fill
 * for a live one (or vice versa) at a glance.
 *
 *   PAPER  → amber
 *   LIVE   → red (rose)
 *   SHADOW → sky-blue (would-have-fired only)
 *   MIXED  → slate (a symbol with rows of multiple types)
 *   UNKNOWN/null → slate
 */
import React from 'react';

const TYPE_STYLE = {
  paper:   'bg-amber-950/60 text-amber-300 border-amber-800',
  live:    'bg-rose-950/60 text-rose-300 border-rose-800',
  shadow:  'bg-sky-950/60 text-sky-300 border-sky-800',
  mixed:   'bg-slate-800 text-slate-200 border-slate-600',
  unknown: 'bg-slate-900/60 text-slate-400 border-slate-700',
};

const TYPE_LABEL = {
  paper:   'PAPER',
  live:    'LIVE',
  shadow:  'SHADOW',
  mixed:   'MIXED',
  unknown: '?',
};

/**
 * Render `null` for unknown when `hideUnknown` is true so callers
 * (Day Tape, Forensics) can keep tables compact unless the row was
 * actually paper / live.
 */
export default function TradeTypeChip({
  type,
  hideUnknown = false,
  size = 'sm',
  testIdSuffix,
  title,
}) {
  const t = String(type || '').toLowerCase();
  if (hideUnknown && (!t || t === 'unknown')) return null;
  const cls = TYPE_STYLE[t] || TYPE_STYLE.unknown;
  const label = TYPE_LABEL[t] || TYPE_LABEL.unknown;
  const padding = size === 'xs'
    ? 'px-1 py-0 text-[9px]'
    : 'px-1.5 py-0 text-[10px]';
  return (
    <span
      data-testid={`trade-type-chip${testIdSuffix ? `-${testIdSuffix}` : ''}`}
      data-trade-type={t || 'unknown'}
      className={`inline-flex items-center uppercase tracking-wider border rounded font-bold ${padding} ${cls}`}
      title={title || `Trade origin: ${label}`}
    >
      {label}
    </span>
  );
}
