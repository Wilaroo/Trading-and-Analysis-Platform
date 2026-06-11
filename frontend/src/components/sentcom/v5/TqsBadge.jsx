/**
 * TqsBadge — v19.34.258 (Part B)
 *
 * The SINGLE primary score indicator on every ticker card face. Replaces
 * the prior scatter of SetupGradeChip / ShadowDecisionBadge / WhyThisSizePill
 * / edge_rank / SMB chips with one trusted Trade Quality Score.
 *
 * Click opens the shared <TqsDrillDownDrawer/> (via tqsDrawerBus) where the
 * full 5-pillar breakdown + folded context lives.
 *
 * v322o — the badge now PREFERS the backend-stamped `tqs_grade`. Since
 * v19.34.228 that grade is CALIBRATED by percentile rank against a rolling
 * 5-day reference (grade_calibration.py): composites compress into ~45-71,
 * so re-deriving the grade here with the static ladder (>=85=A …) undid the
 * calibration and pinned every card at C/C+ even when the backend graded
 * A/B. The static score-ladder remains only as a fallback for legacy rows
 * that carry a score but no grade.
 */
import React from 'react';
import { openTqsDrawer } from './tqsDrawerBus';

// Canonical score → grade ladder (mirrors tqs_router._grade).
export const gradeFromScore = (score) => {
  const s = Number(score);
  if (!Number.isFinite(s)) return '';
  if (s >= 85) return 'A';
  if (s >= 75) return 'B+';
  if (s >= 65) return 'B';
  if (s >= 55) return 'C+';
  if (s >= 45) return 'C';
  if (s >= 35) return 'D';
  return 'F';
};

// Grade → color family (design blueprint: A=emerald, B=sky, C=amber, D/F=rose).
export const gradeTone = (grade) => {
  const g = String(grade || '').toUpperCase();
  if (g === 'A' || g === 'A+') {
    return {
      pill: 'text-emerald-300 border-emerald-600/40 bg-emerald-500/10 hover:bg-emerald-500/15',
      full: 'text-emerald-300 border-emerald-600/40 bg-emerald-500/5',
      fill: 'bg-emerald-500',
    };
  }
  if (g === 'B+' || g === 'B') {
    return {
      pill: 'text-sky-300 border-sky-600/40 bg-sky-500/10 hover:bg-sky-500/15',
      full: 'text-sky-300 border-sky-600/40 bg-sky-500/5',
      fill: 'bg-sky-500',
    };
  }
  if (g === 'C+' || g === 'C') {
    return {
      pill: 'text-amber-300 border-amber-600/40 bg-amber-500/10 hover:bg-amber-500/15',
      full: 'text-amber-300 border-amber-600/40 bg-amber-500/5',
      fill: 'bg-amber-500',
    };
  }
  if (g === 'D' || g === 'F') {
    return {
      pill: 'text-rose-300 border-rose-600/40 bg-rose-500/10 hover:bg-rose-500/15',
      full: 'text-rose-300 border-rose-600/40 bg-rose-500/5',
      fill: 'bg-rose-500',
    };
  }
  return {
    pill: 'text-zinc-400 border-zinc-700 bg-zinc-900/60 hover:bg-zinc-800/60',
    full: 'text-zinc-400 border-zinc-700 bg-zinc-900/60',
    fill: 'bg-zinc-600',
  };
};

/**
 * @param {object} props
 * @param {string} props.symbol
 * @param {number} [props.score]            0-100 TQS score (preferred)
 * @param {string} [props.gradeFallback]    legacy grade if no score available
 * @param {'alert'|'position'} [props.source='alert']
 * @param {'compact'|'full'} [props.variant='compact']
 * @param {string} [props.testIdSuffix='']
 */
const TqsBadge = ({
  symbol,
  score,
  gradeFallback = '',
  source = 'alert',
  variant = 'compact',
  testIdSuffix = '',
}) => {
  const hasScore = score != null && Number.isFinite(Number(score)) && Number(score) > 0;
  // v322o — backend calibrated grade wins; static score-ladder is fallback-only.
  const backendGrade = String(gradeFallback || '').toUpperCase();
  const grade = backendGrade || (hasScore ? gradeFromScore(score) : '');
  const tone = gradeTone(grade);
  const testId = `tqs-badge-card${testIdSuffix ? `-${testIdSuffix}` : ''}`;

  const handleClick = (e) => {
    e.stopPropagation();
    openTqsDrawer({ symbol, source });
  };

  if (variant === 'full') {
    return (
      <button
        type="button"
        data-testid={testId}
        onClick={handleClick}
        className={`flex flex-col items-center justify-center px-4 py-1.5 rounded-md border transition-colors ${tone.full}`}
        title="Open TQS drill-down"
      >
        <span className="v5-mono text-2xl font-bold leading-none">
          {hasScore ? Math.round(Number(score)) : '—'}
        </span>
        {grade && (
          <span className="text-[11px] uppercase tracking-[0.2em] mt-1 font-bold">{grade}</span>
        )}
        <span className="text-[9px] uppercase tracking-wider text-zinc-500 mt-0.5">TQS</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      data-testid={testId}
      onClick={handleClick}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border v5-mono text-[11px] transition-all hover:-translate-y-px ${tone.pill}`}
      title={`TQS ${hasScore ? Math.round(Number(score)) : '?'}${grade ? ` · ${grade}` : ''} — click for drill-down`}
    >
      <span className="opacity-60 text-[9px] uppercase tracking-wider">TQS</span>
      {hasScore && <span className="font-bold">{Math.round(Number(score))}</span>}
      {grade && <span className="font-bold">{grade}</span>}
    </button>
  );
};

export default TqsBadge;
export { TqsBadge };
