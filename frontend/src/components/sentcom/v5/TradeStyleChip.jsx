/**
 * TradeStyleChip — v19.34.99
 *
 * Compact 2-row inline chip showing:
 *   • Setup name (e.g. "Pocket Pivot")        — top line
 *   • Trade-style + horizon                   — bottom line
 *
 * Used in every surface where a row can represent a setup/alert/open
 * position/closed trade so the operator always sees:
 *   1. What type of trade is it     (setup name)
 *   2. What trade style is it       (scalp/intraday/swing/inv/position)
 *   3. What time horizon            (minutes-hours-days-weeks-months)
 *
 * Lookup precedence:
 *   row.trade_style → row.scan_tier → row.tier → derive from row.setup_type
 *
 * Compact mode (`compact={true}`) renders a single inline chip
 * suitable for tight scanner cards: "POS · Stage-2 Breakout" — the
 * full horizon is moved into the `title` tooltip.
 */
import React from 'react';

import { getTradeStyleMeta, humanizeSetupName, resolveTradeStyle } from '../../../utils/tradeStyleMeta';
import { useTaxonomyVersion } from '../../../utils/useTaxonomy';

const TONE_CLASS = {
  fuchsia:  'bg-fuchsia-950/60 text-fuchsia-300 border-fuchsia-800',
  sky:      'bg-sky-950/60 text-sky-300 border-sky-800',
  emerald:  'bg-emerald-950/60 text-emerald-300 border-emerald-800',
  amber:    'bg-amber-950/60 text-amber-300 border-amber-800',
  rose:     'bg-rose-950/60 text-rose-300 border-rose-800',
  slate:    'bg-slate-900/60 text-slate-400 border-slate-700',
};

const TONE_HORIZON_CLASS = {
  fuchsia:  'text-fuchsia-400/80',
  sky:      'text-sky-400/80',
  emerald:  'text-emerald-400/80',
  amber:    'text-amber-400/80',
  rose:     'text-rose-400/80',
  slate:    'text-slate-500',
};

/**
 * Props:
 *   row          : object with trade_style / setup_type / scan_tier etc.
 *   compact      : single-line chip for tight layouts (default false)
 *   showSetup    : include the humanised setup name in the chip (default true)
 *   size         : 'xs' | 'sm' (default 'sm')
 *   testIdSuffix : appended to data-testid for uniqueness in lists
 */
export default function TradeStyleChip({
  row,
  compact = false,
  showSetup = true,
  size = 'sm',
  testIdSuffix,
}) {
  // Re-render when the live SSOT taxonomy hydrates so styles never stay stale.
  useTaxonomyVersion();
  if (!row) return null;
  const meta = getTradeStyleMeta(row);
  const styleKey = resolveTradeStyle(row);
  const setupName = showSetup ? humanizeSetupName(row.setup_type || row.alert_type || '') : '';
  const tone = TONE_CLASS[meta.tone] || TONE_CLASS.slate;
  const toneHorizon = TONE_HORIZON_CLASS[meta.tone] || TONE_HORIZON_CLASS.slate;
  const pad = size === 'xs' ? 'px-1.5 py-0 text-[11px]' : 'px-2 py-0.5 text-[12px]';
  const title = `${setupName ? setupName + ' · ' : ''}${meta.label} (${meta.horizon})`;
  const testId = `trade-style-chip${testIdSuffix ? `-${testIdSuffix}` : ''}`;

  if (compact) {
    return (
      <span
        data-testid={testId}
        data-trade-style={styleKey}
        data-setup-type={row.setup_type || ''}
        title={title}
        className={`inline-flex items-center gap-1 uppercase tracking-wider border rounded font-bold ${pad} ${tone}`}
      >
        <span>{meta.shortKey}</span>
        {setupName && (
          <>
            <span className="opacity-50">·</span>
            <span className="normal-case font-medium">{setupName}</span>
          </>
        )}
      </span>
    );
  }

  return (
    <div
      data-testid={testId}
      data-trade-style={styleKey}
      data-setup-type={row.setup_type || ''}
      title={title}
      className={`inline-flex flex-col items-start border rounded ${pad} ${tone}`}
    >
      {setupName && (
        <span className="font-bold uppercase tracking-wide leading-tight">{setupName}</span>
      )}
      <span className={`leading-tight ${toneHorizon}`}>
        <span className="font-semibold">{meta.label}</span>
        <span className="opacity-60"> · {meta.horizon}</span>
      </span>
    </div>
  );
}
