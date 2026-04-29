/**
 * ShadowDecisionBadge — small chip rendered inline on V5 stream rows
 * showing what the shadow-mode AI modules decided for the same symbol.
 *
 * Visual lexicon (kept tight so it doesn't dominate the row):
 *   • TAKE    (green)  — shadow voted "proceed"
 *   • PASS    (red)    — shadow voted "pass"
 *   • REDUCE  (amber)  — shadow voted "reduce_size"
 *   • Confidence  → numeric tail "0.72"
 *   • Executed?   → small filled-circle marker (●) if was_executed
 *                   else hollow (○) — answers "did the bot agree
 *                   with shadow on this one?"
 *
 * 2026-04-30 v11 — operator-flagged: divergence signal needs to be
 * actionable per-alert, not just aggregate.
 */
import React from 'react';

const RECOMMENDATION_STYLE = {
  proceed: {
    label: 'TAKE',
    cls: 'bg-emerald-950/50 border-emerald-700/60 text-emerald-300',
  },
  pass: {
    label: 'PASS',
    cls: 'bg-rose-950/40 border-rose-800/60 text-rose-300',
  },
  reduce_size: {
    label: 'REDUCE',
    cls: 'bg-amber-950/40 border-amber-800/60 text-amber-300',
  },
};

export const ShadowDecisionBadge = ({ decision, ageMs }) => {
  if (!decision || !decision.recommendation) return null;
  const style = RECOMMENDATION_STYLE[decision.recommendation];
  if (!style) return null;

  const conf = Number(decision.confidence_score);
  const confDisplay = Number.isFinite(conf) && conf > 0
    ? conf.toFixed(2)
    : null;
  const executed = decision.was_executed;

  // Render a freshness microbar — shadow decisions decay fast; show
  // a visual hint when the row's timestamp is more than ~5min off
  // the shadow trigger.
  const stale = typeof ageMs === 'number' && ageMs > 5 * 60 * 1000;

  const title =
    `Shadow ${style.label}` +
    (confDisplay ? ` · conf ${confDisplay}` : '') +
    (executed ? ' · bot agreed (executed)' : ' · bot diverged (skipped)') +
    (stale ? ' · stale signal' : '');

  return (
    <span
      data-testid={`shadow-badge-${decision.recommendation}`}
      className={`inline-flex items-center gap-1 px-1.5 py-px ml-1.5 rounded border text-[9px] font-semibold uppercase tracking-wide ${style.cls} ${stale ? 'opacity-60' : ''}`}
      title={title}
    >
      <span aria-hidden="true">{executed ? '●' : '○'}</span>
      <span>{style.label}</span>
      {confDisplay && (
        <span className="text-[8px] font-mono opacity-80">{confDisplay}</span>
      )}
    </span>
  );
};

export default ShadowDecisionBadge;
