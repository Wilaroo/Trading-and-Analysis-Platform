/**
 * TqsPillarPanel — v19.34.175
 *
 * Operator drill-down for the Trade Quality Score (TQS) — the single
 * source of truth for a trade's grade. Renders the 5 weighted pillars
 * captured at fill time (in `position.entry_context.tqs`) and lets the
 * operator expand each pillar to see its sub-component scores + the
 * +/- factor bullets that drove it.
 *
 *   Setup (25%) · Technical (25%) · Fundamental (15%) ·
 *   Context (20%) · Execution (15%)   ← default weights; the captured
 *   `weights` map reflects the timeframe-aware weights actually used.
 *
 * Data contract — `tqs` (= position.entry_context.tqs):
 *   { score, unified_grade, post_gate_grade, pillar_scores{},
 *     pillar_grades{}, weights{}, breakdown{ pillar: {score, grade,
 *     components{name:score}, factors[] } } }
 *
 * Renders nothing when no TQS data was captured for the trade
 * (legacy/synthetic fills predating v19.34.175).
 */
import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

// Canonical pillar order (matches services/tqs/tqs_engine.py weighting).
const PILLAR_ORDER = ['setup', 'technical', 'fundamental', 'context', 'execution'];

// Static fallbacks if the /api/tqs/pillars roster hasn't loaded yet.
const PILLAR_FALLBACK = {
  setup: { name: 'Setup Quality', weight: '25%' },
  technical: { name: 'Technical Quality', weight: '25%' },
  fundamental: { name: 'Fundamental Quality', weight: '15%' },
  context: { name: 'Context Quality', weight: '20%' },
  execution: { name: 'Execution Quality', weight: '15%' },
};

const GRADE_TONE = {
  A: 'text-emerald-300 border-emerald-700 bg-emerald-950/50',
  'B+': 'text-sky-300 border-sky-700 bg-sky-950/50',
  B: 'text-sky-400 border-sky-800/60 bg-sky-950/40',
  'C+': 'text-amber-300 border-amber-700 bg-amber-950/50',
  C: 'text-amber-400 border-amber-800/60 bg-amber-950/40',
  D: 'text-orange-300 border-orange-800 bg-orange-950/50',
  F: 'text-rose-300 border-rose-700 bg-rose-950/50',
};

const gradeTone = (g) => GRADE_TONE[(g || '').toUpperCase()] || 'text-zinc-400 border-zinc-700 bg-zinc-900/60';

// Score → bar color. Mirrors the operator's emerald/amber/rose mental model.
const barColor = (score) => {
  const s = Number(score) || 0;
  if (s >= 75) return 'bg-emerald-500';
  if (s >= 60) return 'bg-sky-500';
  if (s >= 45) return 'bg-amber-500';
  return 'bg-rose-500';
};

const humanizeComponent = (key) =>
  String(key || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());

// Module-level cache — the pillar roster is static config, fetch once.
let _pillarMetaPromise = null;
const fetchPillarMeta = () => {
  if (!_pillarMetaPromise) {
    const base = process.env.REACT_APP_BACKEND_URL || '';
    _pillarMetaPromise = fetch(`${base}/api/tqs/pillars`)
      .then((r) => (r.ok ? r.json() : { pillars: {} }))
      .then((d) => d.pillars || {})
      .catch(() => ({}));
  }
  return _pillarMetaPromise;
};

const PillarRow = ({ pillarKey, meta, breakdown, score, grade, weight, testIdSuffix }) => {
  const [open, setOpen] = useState(false);
  const components = (breakdown && breakdown.components) || {};
  const factors = (breakdown && Array.isArray(breakdown.factors)) ? breakdown.factors : [];
  const hasDetail = Object.keys(components).length > 0 || factors.length > 0;
  const scoreNum = score != null ? Math.round(Number(score)) : null;
  const testId = `tqs-pillar-${pillarKey}-${testIdSuffix}`;

  return (
    <div className="border-b border-zinc-800/60 last:border-b-0">
      <button
        type="button"
        data-testid={`${testId}-toggle`}
        onClick={(e) => { e.stopPropagation(); if (hasDetail) setOpen((v) => !v); }}
        className={`w-full flex items-center gap-2 py-1.5 text-left transition-colors ${hasDetail ? 'hover:bg-zinc-900/50 cursor-pointer' : 'cursor-default'}`}
      >
        <span className="w-3 shrink-0 text-zinc-600">
          {hasDetail ? (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : null}
        </span>
        <span className="w-[120px] shrink-0 text-[12px] text-zinc-300 truncate" title={meta.name}>
          {meta.name}
        </span>
        <span className="w-[34px] shrink-0 text-[11px] text-zinc-600 v5-mono">{weight}</span>
        <span className="flex-1 h-1.5 bg-zinc-800 rounded-sm overflow-hidden">
          {scoreNum != null && (
            <span
              className={`block h-full ${barColor(scoreNum)} transition-all`}
              style={{ width: `${Math.max(2, Math.min(100, scoreNum))}%` }}
            />
          )}
        </span>
        <span className="w-[34px] shrink-0 text-right text-[12px] text-zinc-300 v5-mono">
          {scoreNum != null ? scoreNum : '—'}
        </span>
        {grade && (
          <span className={`shrink-0 px-1 py-0 text-[10px] uppercase rounded-sm border ${gradeTone(grade)}`}>
            {grade}
          </span>
        )}
      </button>

      {open && hasDetail && (
        <div
          className="ml-5 mb-2 pl-3 border-l border-zinc-800 space-y-1.5"
          data-testid={`${testId}-detail`}
        >
          {Object.keys(components).length > 0 && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 pt-1">
              {Object.entries(components).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between text-[11px]">
                  <span className="text-zinc-500 truncate">{humanizeComponent(k)}</span>
                  <span className="text-zinc-300 v5-mono ml-2">{Math.round(Number(v) || 0)}</span>
                </div>
              ))}
            </div>
          )}
          {factors.length > 0 && (
            <div className="space-y-0.5 pt-0.5">
              {factors.slice(0, 6).map((f, i) => (
                <div key={i} className="text-[11px] text-zinc-400 leading-snug">
                  <span className="text-zinc-600 mr-1">·</span>{String(f)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const TqsPillarPanel = ({ tqs, testIdSuffix = '' }) => {
  const [meta, setMeta] = useState({});

  useEffect(() => {
    let cancelled = false;
    fetchPillarMeta().then((m) => { if (!cancelled) setMeta(m); });
    return () => { cancelled = true; };
  }, []);

  if (!tqs || typeof tqs !== 'object') return null;

  const breakdown = tqs.breakdown || {};
  const pillarScores = tqs.pillar_scores || {};
  const pillarGrades = tqs.pillar_grades || {};
  const weights = tqs.weights || {};

  // Only render when we actually captured pillar-level data.
  const hasPillars =
    Object.keys(breakdown).length > 0 || Object.keys(pillarScores).length > 0;
  if (!hasPillars) return null;

  const overallScore = tqs.score != null
    ? Math.round(Number(tqs.score))
    : (tqs.post_gate_score != null ? Math.round(Number(tqs.post_gate_score)) : null);
  const overallGrade = tqs.unified_grade || tqs.post_gate_grade || '';

  const weightLabel = (key) => {
    const w = weights[key];
    if (w != null) {
      const pct = Number(w) <= 1 ? Number(w) * 100 : Number(w);
      return `${Math.round(pct)}%`;
    }
    return (PILLAR_FALLBACK[key] && PILLAR_FALLBACK[key].weight) || '';
  };

  return (
    <div
      className="mt-2 rounded-md border border-zinc-800 bg-zinc-950/60 px-3 py-2"
      data-testid={`tqs-pillar-panel-${testIdSuffix}`}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] uppercase tracking-wider text-zinc-500">
          Trade Quality Score
        </span>
        <span className="flex items-center gap-2">
          {overallScore != null && (
            <span className="text-[13px] text-zinc-200 v5-mono font-semibold">{overallScore}</span>
          )}
          {overallGrade && (
            <span className={`px-1.5 py-0 text-[11px] uppercase rounded-sm border font-bold ${gradeTone(overallGrade)}`}>
              {overallGrade}
            </span>
          )}
        </span>
      </div>

      <div>
        {PILLAR_ORDER.map((key) => {
          const pmeta = meta[key] || PILLAR_FALLBACK[key] || { name: key };
          const pb = breakdown[key] || {};
          const score = pb.score != null ? pb.score : pillarScores[key];
          if (score == null && !pb.grade && !pillarGrades[key]) return null;
          return (
            <PillarRow
              key={key}
              pillarKey={key}
              meta={pmeta}
              breakdown={pb}
              score={score}
              grade={pb.grade || pillarGrades[key] || ''}
              weight={weightLabel(key)}
              testIdSuffix={testIdSuffix}
            />
          );
        })}
      </div>
    </div>
  );
};

export default TqsPillarPanel;
export { TqsPillarPanel };
