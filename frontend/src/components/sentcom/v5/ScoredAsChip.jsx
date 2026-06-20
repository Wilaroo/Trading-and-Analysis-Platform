/**
 * ScoredAsChip — v19.34.272 (UI Track A / P1 "Scored as")
 *
 * Surfaces the PATTERN-INTRINSIC grading style TQS used to WEIGHT the score
 * (mirrors backend services/setup_taxonomy.style_of) — deliberately DISTINCT
 * from the liquidity horizon stamp shown by <TradeStyleChip/>.
 *
 * This makes the P1 Style=Pattern fix visible on every row/drawer: e.g. a
 * `breakdown_confirmed` on a highly-liquid name reads horizon = INTRA but is
 * SCORED M-DAY (fundamentals weighted heavier) because the pattern is multi-day.
 *
 * Source precedence (see utils/tradeStyleMeta.gradingStyleKey):
 *   persisted tqs_breakdown.scoring_style → setup-derived pattern style
 *   (via the live SSOT taxonomy bridge). Renders nothing when unknown.
 */
import React from 'react';

import { getGradingStyleMeta, gradingStyleKey } from '../../../utils/tradeStyleMeta';
import { useTaxonomyVersion } from '../../../utils/useTaxonomy';

const TONE_CLASS = {
  fuchsia: 'bg-fuchsia-950/50 text-fuchsia-300 border-fuchsia-800/70',
  sky:     'bg-sky-950/50 text-sky-300 border-sky-800/70',
  emerald: 'bg-emerald-950/50 text-emerald-300 border-emerald-800/70',
  amber:   'bg-amber-950/50 text-amber-300 border-amber-800/70',
  rose:    'bg-rose-950/50 text-rose-300 border-rose-800/70',
  slate:   'bg-slate-900/60 text-slate-400 border-slate-700',
};

/**
 * Props:
 *   row          : object with scoring_style / tqs_breakdown / setup_type
 *   size         : 'xs' | 'sm' (default 'xs')
 *   testIdSuffix : appended to data-testid for uniqueness in lists
 */
export default function ScoredAsChip({ row, size = 'xs', testIdSuffix }) {
  // Re-render once the live SSOT taxonomy hydrates so the style never stays stale.
  useTaxonomyVersion();
  if (!row) return null;

  const key = gradingStyleKey(row);
  if (!key || key === 'unknown') return null;

  const meta = getGradingStyleMeta(row);
  const tone = TONE_CLASS[meta.tone] || TONE_CLASS.slate;
  const pad = size === 'sm' ? 'px-2 py-0.5 text-[12px]' : 'px-1.5 py-0 text-[11px]';
  const testId = `scored-as-chip${testIdSuffix ? `-${testIdSuffix}` : ''}`;
  const label = String(meta.label || '').toLowerCase();
  const title =
    `Scored as ${meta.label} — TQS weighted this trade for a ${label} hold (${meta.horizon}) ` +
    `because the setup pattern is ${label}. Liquidity sets the horizon; the pattern sets the grade.`;

  return (
    <span
      data-testid={testId}
      data-grading-style={key}
      title={title}
      className={`inline-flex items-center gap-1 uppercase tracking-wider border rounded font-bold ${pad} ${tone}`}
    >
      <span className="opacity-60 text-[9px]">SCORED</span>
      <span>{meta.shortKey}</span>
    </span>
  );
}
