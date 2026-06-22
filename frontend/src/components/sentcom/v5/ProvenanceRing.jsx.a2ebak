/**
 * ProvenanceRing — v19.34.273 (UI Track A / A2) · v19.34.276 scalable rail
 *
 * Compact SVG "provenance ring": 5 equal arcs, one per TQS pillar
 * (setup · technical · fundamental · context · execution), each colored by
 * that pillar's grade. The overall TQS grade letter sits in the center.
 *
 * It answers "where does this score come from?" at a glance — the
 * <TqsBadge/> still shows the precise number; this shows its composition.
 * Click opens the shared <TqsDrillDownDrawer/> (via tqsDrawerBus).
 *
 * Renders nothing when no per-pillar grades were captured (legacy rows).
 * Data source: alert/position `tqs_pillar_grades` (asdict from the backend).
 *
 * Sizing: pass `size` (px) for a fixed badge, OR `fill` to make the SVG fill
 * its parent (100% × 100%) so the caller can scale it to e.g. full card
 * height. Geometry uses a fixed 100×100 nominal coordinate space so arcs,
 * stroke and the center letter scale proportionally at any rendered size.
 */
import React from 'react';

import { openTqsDrawer } from './tqsDrawerBus';
import { gradeFromScore } from './TqsBadge';

// Canonical pillar order — matches services/tqs/tqs_engine.py + TqsPillarPanel.
const PILLAR_ORDER = ['setup', 'technical', 'fundamental', 'context', 'execution'];
const PILLAR_LABEL = {
  setup: 'Setup',
  technical: 'Technical',
  fundamental: 'Fundamental',
  context: 'Context',
  execution: 'Execution',
};

// Grade → stroke color (mirrors TqsBadge.gradeTone families).
const GRADE_STROKE = {
  'A+': '#10b981', A: '#10b981',
  'B+': '#0ea5e9', B: '#0ea5e9',
  'C+': '#f59e0b', C: '#f59e0b',
  D: '#f97316',
  F: '#f43f5e',
};
const MISSING = '#3f3f46'; // zinc-700 — pillar with no grade
const strokeFor = (g) => GRADE_STROKE[String(g || '').toUpperCase()] || MISSING;

const polar = (cx, cy, r, deg) => {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
};
const arcPath = (cx, cy, r, startDeg, endDeg) => {
  const [x1, y1] = polar(cx, cy, r, startDeg);
  const [x2, y2] = polar(cx, cy, r, endDeg);
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
};

/**
 * Props:
 *   symbol, source           : for the drawer
 *   pillarGrades             : { setup, technical, fundamental, context, execution }
 *   grade                    : overall TQS grade (center letter); falls back to score
 *   score                    : overall TQS score (used if grade missing)
 *   size                     : px diameter (default 28) — ignored when `fill`
 *   fill                     : when true the SVG fills its parent (100% × 100%)
 *   className                : extra classes on the button (sizing in fill mode)
 *   testIdSuffix
 */
export default function ProvenanceRing({
  symbol,
  source = 'alert',
  pillarGrades,
  grade = '',
  score = null,
  size = 28,
  fill = false,
  className = '',
  testIdSuffix,
}) {
  const grades = pillarGrades && typeof pillarGrades === 'object' ? pillarGrades : null;
  const hasAny = grades && PILLAR_ORDER.some((k) => grades[k]);
  if (!hasAny) return null;

  const centerGrade = String(grade || (score != null ? gradeFromScore(score) : '') || '').toUpperCase();
  // Fixed 100×100 nominal space → ring scales cleanly via CSS (fixed `size`
  // px OR `fill` = 100% of its container).
  const NOM = 100;
  const sw = NOM * 0.11;
  const c = NOM / 2;
  const r = c - sw / 2 - 0.5;
  const gap = 9; // degrees between segments
  const seg = 360 / PILLAR_ORDER.length;
  const testId = `provenance-ring${testIdSuffix ? `-${testIdSuffix}` : ''}`;
  const svgDim = fill ? '100%' : size;

  const title =
    'Provenance — ' +
    PILLAR_ORDER.map((k) => `${PILLAR_LABEL[k]} ${grades[k] || '—'}`).join(' · ');

  const handleClick = (e) => {
    e.stopPropagation();
    if (symbol) openTqsDrawer({ symbol, source });
  };

  return (
    <button
      type="button"
      data-testid={testId}
      onClick={handleClick}
      title={title}
      aria-label={title}
      className={`shrink-0 rounded-full transition-transform hover:scale-105 focus:outline-none ${className}`}
      style={fill ? { lineHeight: 0 } : { width: size, height: size, lineHeight: 0 }}
    >
      <svg width={svgDim} height={svgDim} viewBox={`0 0 ${NOM} ${NOM}`} style={{ display: 'block' }}>
        {/* track */}
        <circle cx={c} cy={c} r={r} fill="none" stroke="#18181b" strokeWidth={sw} />
        {/* pillar arcs */}
        {PILLAR_ORDER.map((k, i) => {
          const start = i * seg + gap / 2;
          const end = (i + 1) * seg - gap / 2;
          return (
            <path
              key={k}
              d={arcPath(c, c, r, start, end)}
              fill="none"
              stroke={strokeFor(grades[k])}
              strokeWidth={sw}
              strokeLinecap="round"
              data-pillar={k}
              data-grade={grades[k] || ''}
            />
          );
        })}
        {/* center grade letter */}
        {centerGrade && (
          <text
            x={c}
            y={c}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={NOM * 0.34}
            fontWeight="700"
            fill={strokeFor(centerGrade)}
            fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
          >
            {centerGrade}
          </text>
        )}
      </svg>
    </button>
  );
}
