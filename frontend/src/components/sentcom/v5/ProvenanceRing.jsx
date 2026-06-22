/**
 * ProvenanceRing — v19.34.273 (UI Track A / A2) · v19.34.276 scalable rail
 *
 * Compact SVG "provenance ring": 5 equal arcs, one per TQS pillar
 * (setup · technical · fundamental · context · execution). Each pillar has a
 * FIXED identity color (5 always-distinct hues) and its grade drives the bright
 * fill length over a faint track, so the ring shows composition AND per-pillar
 * strength at a glance. The overall TQS grade letter sits in the center.
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
// Chosen so every band is clearly distinguishable on the dark card — in
// particular C (yellow) vs D (orange), which previously read as one color.
const GRADE_STROKE = {
  'A+': '#22c55e', A: '#22c55e', // green-500
  'B+': '#38bdf8', B: '#38bdf8', // sky-400
  'C+': '#facc15', C: '#facc15', // yellow-400 (clearly yellow)
  D: '#f97316',                  // orange-500 (clearly orange)
  F: '#ef4444',                  // red-500
};
const MISSING = '#52525b'; // zinc-600 — visible neutral arc for an ungraded pillar
const strokeFor = (g) => GRADE_STROKE[String(g || '').toUpperCase()] || MISSING;

// v19.34.284 (A2k-ring) — each TQS pillar gets a FIXED identity color so the ring
// always shows 5 distinct hues. Previously arcs were colored by GRADE, so
// same-grade pillars (e.g. Technical B vs Context C+, or Setup D vs Execution F)
// read as a single color and the ring looked like ~3 colors instead of 5. The
// per-pillar grade now drives the bright fill LENGTH over a faint full track, so
// you still see weak (short) vs strong (full) pillars at a glance.
const PILLAR_COLOR = {
  setup: '#8b5cf6', // violet-500
  technical: '#22d3ee', // cyan-400
  fundamental: '#f59e0b', // amber-500
  context: '#34d399', // emerald-400
  execution: '#fb7185', // rose-400
};
const GRADE_FRAC = {
  'A+': 1.0, A: 0.95, 'B+': 0.84, B: 0.76, 'C+': 0.62, C: 0.54, D: 0.40, F: 0.24,
};
const fracFor = (g) => GRADE_FRAC[String(g || '').toUpperCase()] ?? 0;

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
  // Center shows the numeric TQS score (the "TQS number") when available, so
  // the ring is self-explanatory; the grade letter still lives on the chip.
  // Falls back to the grade letter for rows that only carry a grade.
  const hasScore = score != null && !Number.isNaN(Number(score));
  const centerText = hasScore ? String(Math.round(Number(score))) : centerGrade;
  const centerFont = centerText.length >= 3 ? NOM * 0.26 : NOM * 0.34;

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
        {/* pillar arcs — v19.34.284 (A2k-ring): each pillar has a FIXED identity
            hue (5 always-distinct colors) and its GRADE drives the bright fill
            length over a faint full-segment track, so the ring reads as 5 colors
            at a glance while still showing weak (short) vs strong (full) pillars. */}
        {PILLAR_ORDER.map((k, i) => {
          const start = i * seg + gap / 2;
          const end = (i + 1) * seg - gap / 2;
          const col = PILLAR_COLOR[k];
          const frac = fracFor(grades[k]);
          const fillEnd = start + (end - start) * frac;
          return (
            <g key={k} data-pillar={k} data-grade={grades[k] || ''}>
              <path
                d={arcPath(c, c, r, start, end)}
                fill="none"
                stroke={col}
                strokeOpacity={0.2}
                strokeWidth={sw}
                strokeLinecap="round"
              />
              {frac > 0.001 && (
                <path
                  d={arcPath(c, c, r, start, fillEnd)}
                  fill="none"
                  stroke={col}
                  strokeWidth={sw}
                  strokeLinecap="round"
                />
              )}
            </g>
          );
        })}
        {/* center: numeric TQS score with the grade letter beneath it (when
            both are known); grade-only rows show just the letter, centered. */}
        {hasScore ? (
          <>
            <text
              x={c}
              y={c - NOM * 0.09}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={centerFont}
              fontWeight="700"
              fill={strokeFor(centerGrade)}
              fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
            >
              {centerText}
            </text>
            {centerGrade && (
              <text
                x={c}
                y={c + NOM * 0.22}
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={NOM * 0.22}
                fontWeight="700"
                fill={strokeFor(centerGrade)}
                opacity="0.9"
                fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
              >
                {centerGrade}
              </text>
            )}
          </>
        ) : (
          centerText && (
            <text
              x={c}
              y={c}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={NOM * 0.40}
              fontWeight="700"
              fill={strokeFor(centerGrade)}
              fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
            >
              {centerText}
            </text>
          )
        )}
      </svg>
    </button>
  );
}
