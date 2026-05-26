/**
 * WhyThisSizePill — v19.34.159 (Feb 2026)
 *
 * Compact hover pill that surfaces the position-sizing multiplier chain
 * stamped onto each trade in `entry_context.multipliers`:
 *
 *     grade (v156) × volatility × regime × vp_path × mr_regime (v157)
 *     = final scalar applied to the base share count
 *
 * Renders nothing when no multipliers are present (legacy pre-v156
 * trades). Click toggles a sticky popover; hover shows the title-attr
 * fallback (matches the existing PortfolioHealthPill convention).
 *
 * Data source: `position.entry_context.multipliers` (server stamps this
 * in `opportunity_evaluator.build_entry_context`).
 */
import React, { useMemo, useState } from 'react';
import { Sigma } from 'lucide-react';

const fmtMult = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n.toFixed(2)}×`;
};

const fmtNum = (v, digits = 2) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  return Number(v).toFixed(digits);
};

const Row = ({ label, mult, detail, dim }) => (
  <div
    data-testid={`why-size-row-${label.toLowerCase().replace(/\s+/g, '-')}`}
    className={`flex items-center justify-between gap-3 px-2 py-1 ${dim ? 'text-zinc-500' : 'text-zinc-200'}`}
  >
    <span className="text-[12px] uppercase tracking-wider">{label}</span>
    <span className="flex items-center gap-2">
      {detail && <span className="text-[11px] text-zinc-500">{detail}</span>}
      <span className="v5-mono text-[13px]">{fmtMult(mult)}</span>
    </span>
  </div>
);

export const WhyThisSizePill = ({ multipliers }) => {
  const [open, setOpen] = useState(false);

  const m = multipliers || {};
  const hasAny = useMemo(() => {
    return ['grade_multiplier', 'volatility', 'regime', 'vp_path', 'mr_multiplier']
      .some((k) => m[k] != null);
  }, [m]);

  const product = useMemo(() => {
    const keys = ['grade_multiplier', 'volatility', 'regime', 'vp_path', 'mr_multiplier'];
    let p = 1.0;
    let any = false;
    for (const k of keys) {
      const v = Number(m[k]);
      if (!Number.isNaN(v) && v !== 0) {
        p *= v;
        any = true;
      }
    }
    return any ? p : null;
  }, [m]);

  const tooltip = useMemo(() => {
    if (!hasAny) return '';
    const lines = ['Why this size? (sizing scalars compose multiplicatively)'];
    if (m.grade) lines.push(`Grade ${m.grade}: ${fmtMult(m.grade_multiplier)}`);
    if (m.volatility != null) lines.push(`Volatility: ${fmtMult(m.volatility)}`);
    if (m.regime != null) lines.push(`Regime: ${fmtMult(m.regime)}`);
    if (m.vp_path != null) lines.push(`VP path: ${fmtMult(m.vp_path)}`);
    if (m.mr_regime) lines.push(`MR ${m.mr_regime}: ${fmtMult(m.mr_multiplier)}`);
    if (product != null) lines.push('─', `Final: ${fmtMult(product)}`);
    return lines.join('\n');
  }, [hasAny, m, product]);

  if (!hasAny) return null;

  return (
    <span
      data-testid="why-this-size-pill"
      className="relative inline-flex items-center"
      title={tooltip}
    >
      <button
        type="button"
        data-testid="why-this-size-toggle"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className="inline-flex items-center gap-1 px-1.5 py-0.5 border border-zinc-700/60 bg-zinc-900/40 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 transition text-[11px] uppercase tracking-wider"
      >
        <Sigma className="w-3 h-3" />
        <span>why {fmtMult(product)}</span>
      </button>

      {open && (
        <div
          data-testid="why-this-size-popover"
          onClick={(e) => e.stopPropagation()}
          className="absolute z-50 left-0 top-full mt-1 w-[280px] bg-zinc-950 border border-zinc-700 shadow-2xl p-2 text-[13px] cursor-default"
        >
          <div className="flex items-center justify-between mb-1 px-2">
            <span className="text-zinc-500 uppercase tracking-wider text-[11px]">
              Sizing breakdown
            </span>
            <button
              type="button"
              data-testid="why-this-size-close"
              onClick={(e) => { e.stopPropagation(); setOpen(false); }}
              className="text-zinc-600 hover:text-zinc-200 text-[12px]"
              title="Close"
            >
              ×
            </button>
          </div>

          {m.grade_multiplier != null && (
            <Row label="Grade" mult={m.grade_multiplier} detail={m.grade || ''} />
          )}
          {m.volatility != null && (
            <Row label="Volatility" mult={m.volatility} />
          )}
          {m.regime != null && (
            <Row label="Regime" mult={m.regime} />
          )}
          {m.vp_path != null && (
            <Row label="VP path" mult={m.vp_path} />
          )}
          {m.mr_multiplier != null && (
            <Row
              label="MR regime"
              mult={m.mr_multiplier}
              detail={m.mr_regime || ''}
            />
          )}

          {(m.mr_hurst != null || m.mr_half_life_bars != null) && (
            <div className="mt-1 pt-1 border-t border-zinc-800 px-2 text-[11px] text-zinc-500 space-y-0.5">
              {m.mr_hurst != null && (
                <div className="flex justify-between gap-2">
                  <span>Hurst</span>
                  <span className="v5-mono">{fmtNum(m.mr_hurst, 3)}</span>
                </div>
              )}
              {m.mr_half_life_bars != null && (
                <div className="flex justify-between gap-2">
                  <span>Half-life</span>
                  <span className="v5-mono">{fmtNum(m.mr_half_life_bars, 1)} bars</span>
                </div>
              )}
            </div>
          )}

          <div className="mt-1 pt-1 border-t border-zinc-800 flex items-center justify-between px-2">
            <span className="text-[12px] uppercase tracking-wider text-zinc-300">Final</span>
            <span
              data-testid="why-this-size-final"
              className={`v5-mono text-[13px] ${product != null && product < 1 ? 'text-amber-300' : product != null && product > 1 ? 'text-emerald-300' : 'text-zinc-200'}`}
            >
              {fmtMult(product)}
            </span>
          </div>

          {m.mr_reason && (
            <div className="mt-1 px-2 text-[10px] italic text-zinc-600 break-words">
              {String(m.mr_reason)}
            </div>
          )}
        </div>
      )}
    </span>
  );
};

export default WhyThisSizePill;
