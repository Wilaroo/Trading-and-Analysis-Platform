/**
 * QuoteFreshnessChip — v19.34.2 (2026-05-04)
 *
 * Inline chip that visually surfaces how fresh a position's last L1
 * quote is. Pre-v19.34.2 the operator had to mentally derive this
 * from the "STALE" badge that only kicked in past 30s — by which
 * point the bot's manage-loop had already been blind for half a
 * minute. This chip shows the actual age:
 *
 *   < 5s    → cyan  · "FRESH"   · pulse animation when < 2s
 *   5-30s   → amber · "AMBER"   · "Xs old"
 *   ≥ 30s   → red   · "STALE"   · "Xs old"
 *   missing → slate · "?"       · no quote known
 *
 * Used in OpenPositionsV5 row header next to the trade-type chip so
 * the operator can spot a position the bot can't protect at a glance.
 */
import React from 'react';

const _STATE = {
  fresh: {
    cls: 'bg-cyan-950/60 text-cyan-300 border-cyan-800',
    label: 'FRESH',
    dot: 'bg-cyan-400',
  },
  amber: {
    cls: 'bg-amber-950/60 text-amber-300 border-amber-800',
    label: 'AMBER',
    dot: 'bg-amber-400',
  },
  stale: {
    cls: 'bg-rose-950/60 text-rose-300 border-rose-800',
    label: 'STALE',
    dot: 'bg-rose-400',
  },
  unknown: {
    cls: 'bg-slate-900/60 text-slate-400 border-slate-700',
    label: '?',
    dot: 'bg-slate-500',
  },
};

const _fmtAge = (s) => {
  if (s == null) return null;
  const n = Number(s);
  if (!Number.isFinite(n)) return null;
  if (n < 1) return '<1s old';
  if (n < 60) return `${Math.round(n)}s old`;
  const m = Math.floor(n / 60);
  const sec = Math.round(n % 60);
  return sec ? `${m}m ${sec}s old` : `${m}m old`;
};

export default function QuoteFreshnessChip({
  state,
  ageSeconds,
  size = 'xs',
  testIdSuffix,
}) {
  const t = String(state || 'unknown').toLowerCase();
  const conf = _STATE[t] || _STATE.unknown;
  const ageLabel = _fmtAge(ageSeconds);
  const padding = size === 'xs' ? 'px-1.5 py-0 text-[10px]' : 'px-2 py-0 text-[11px]';
  const pulse = t === 'fresh' && Number(ageSeconds) < 2 ? 'animate-pulse' : '';
  return (
    <span
      data-testid={`quote-freshness-chip${testIdSuffix ? `-${testIdSuffix}` : ''}`}
      data-state={t}
      data-age-s={ageSeconds ?? ''}
      className={`inline-flex items-center gap-1 uppercase tracking-wider border rounded font-bold ${padding} ${conf.cls}`}
      title={
        t === 'unknown'
          ? 'No quote available — pusher may not be subscribed to this symbol'
          : `Last quote: ${ageLabel || 'unknown'} (${conf.label.toLowerCase()})`
      }
    >
      <span aria-hidden className={`inline-block w-1.5 h-1.5 rounded-full ${conf.dot} ${pulse}`} />
      <span data-testid="quote-freshness-chip-label">{conf.label}</span>
      {ageLabel && (
        <span
          data-testid="quote-freshness-chip-age"
          className="font-mono opacity-80 normal-case tracking-normal"
        >
          · {ageLabel}
        </span>
      )}
    </span>
  );
}
