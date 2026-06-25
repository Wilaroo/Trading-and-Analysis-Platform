/**
 * EdgeProvenanceRing — V6 ⑧ decision donut for the Entry Edge Score (1C).
 *
 * A single-segment "decision donut" (locked spec ⑧ Verdict-block ring + C scanner
 * mini-arc) that surfaces the Edge TRIPLE at a glance:
 *   • center  = the per-archetype GRADE (0–100 percentile, the single number)
 *   • arc     = grade fill fraction over a faint track
 *   • color   = the GO / STAND-DOWN verdict (emerald vs rose)
 *   • glyph   = colorblind redundancy ✓ / ✕ (locked spec J)
 *   • pips    = confidence band (3 = high, 2 = medium, 1 = low)
 *
 * Distinct from the v5 TQS pillar ring (5 arcs); the Edge Score replaced TQS as the
 * GO authority, so the donut shows the DECISION, not the old composite.
 * Renders a muted "scoring…" ring when no triple is present yet.
 *
 * Geometry uses a fixed 100×100 nominal space → scales cleanly via `size` px or
 * `fill` (100% of parent).
 */
import React from 'react';

const VERDICT = {
  GO: { color: '#34d399', glyph: '✓', label: 'GO' },           // emerald-400
  STAND_DOWN: { color: '#fb7185', glyph: '✕', label: 'STAND-DOWN' }, // rose-400
  NONE: { color: '#52525b', glyph: '·', label: 'scoring…' },   // zinc-600
};
const CONF_PIPS = { high: 3, medium: 2, low: 1 };

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

export default function EdgeProvenanceRing({
  triple,
  size = 30,
  fill = false,
  onClick,
  className = '',
  testIdSuffix,
}) {
  const v = triple?.verdict && VERDICT[triple.verdict] ? VERDICT[triple.verdict] : VERDICT.NONE;
  const grade = triple && triple.grade != null ? Math.round(Number(triple.grade)) : null;
  const frac = grade != null ? Math.max(0, Math.min(1, grade / 100)) : 0;
  const pips = triple ? (CONF_PIPS[String(triple.confidence || '').toLowerCase()] || 0) : 0;

  const NOM = 100;
  const sw = NOM * 0.105;
  const c = NOM / 2;
  const r = c - sw / 2 - 1;
  const sweep = 359.9 * frac;
  const svgDim = fill ? '100%' : size;
  const centerText = grade != null ? String(grade) : '–';
  const centerFont = centerText.length >= 3 ? NOM * 0.3 : NOM * 0.4;
  const testId = `edge-ring${testIdSuffix ? `-${testIdSuffix}` : ''}`;
  const title = triple
    ? `Edge ${v.label} · grade ${grade ?? '—'} · ${triple.confidence || '—'} confidence`
    : 'Edge — scoring…';

  const Wrapper = onClick ? 'button' : 'div';
  return (
    <Wrapper
      type={onClick ? 'button' : undefined}
      data-testid={testId}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(e); } : undefined}
      title={title}
      aria-label={title}
      className={`shrink-0 rounded-full transition-transform ${onClick ? 'hover:scale-105 cursor-pointer' : ''} focus:outline-none ${className}`}
      style={fill ? { lineHeight: 0 } : { width: size, height: size, lineHeight: 0 }}
    >
      <svg width={svgDim} height={svgDim} viewBox={`0 0 ${NOM} ${NOM}`} style={{ display: 'block' }}>
        {/* faint full track */}
        <circle cx={c} cy={c} r={r} fill="none" stroke="#27272a" strokeWidth={sw} />
        {/* grade-fill arc, colored by verdict */}
        {frac > 0.001 && (
          <path
            d={arcPath(c, c, r, 0.1, sweep)}
            fill="none"
            stroke={v.color}
            strokeWidth={sw}
            strokeLinecap="round"
          />
        )}
        {/* center grade number */}
        <text
          x={c}
          y={c - (triple ? NOM * 0.05 : 0)}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={centerFont}
          fontWeight="700"
          fill={v.color}
          fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        >
          {centerText}
        </text>
        {/* verdict glyph (colorblind redundancy) */}
        {triple && (
          <text
            x={c}
            y={c + NOM * 0.24}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={NOM * 0.2}
            fontWeight="700"
            fill={v.color}
            opacity="0.95"
          >
            {v.glyph}
          </text>
        )}
        {/* confidence pips (top arc) */}
        {pips > 0 && [...Array(3)].map((_, i) => {
          const on = i < pips;
          const [px, py] = polar(c, c, r - sw - 2, -18 + i * 18);
          return (
            <circle key={i} cx={px} cy={py} r={NOM * 0.028}
              fill={on ? v.color : '#3f3f46'} opacity={on ? 0.95 : 0.5} />
          );
        })}
      </svg>
    </Wrapper>
  );
}
