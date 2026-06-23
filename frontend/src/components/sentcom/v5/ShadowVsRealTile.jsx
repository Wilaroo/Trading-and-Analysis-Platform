/**
 * ShadowVsRealTile — head-to-head comparison of shadow-mode AI decisions
 * vs the bot's actual closed-trade performance.
 *
 * Why: V5 had no surface to answer the operator's question
 *      "are my AI modules actually edging the live tape, or just
 *       backseat-driving?". Shadow tracker logs every decision the AI
 *      modules WOULD have made in autonomous mode; the trading bot
 *      records every trade it ACTUALLY took. This tile puts the two
 *      win-rates side-by-side so the divergence is visible at a glance.
 *
 * Data sources:
 *   GET /api/ai-modules/shadow/stats     → shadow decisions + win-rate
 *   GET /api/trading-bot/stats/performance → real bot win-rate + P&L
 *
 * Behaviour:
 *   - Polls every 60s (these are slow-changing aggregates).
 *   - Renders compact when both sources are stable; emits a
 *     "shadow ahead" / "shadow behind" / "in sync" signal.
 *   - Silent on either source missing — never blocks layout.
 *
 * 2026-04-30 (operator P1): wired into the V5 sidebar tile column.
 */
import React, { useState, useEffect, useRef } from 'react';
import { Eye, Activity, TrendingUp, TrendingDown, Minus, GitBranch } from 'lucide-react';
import api from '../../../utils/api';

const POLL_INTERVAL_MS = 60_000;

// P3 Seam-3 — arm display order + palette. champion = live dual-gate
// (baseline), unified_1a2a = the proposed single-authority verdict,
// gate_off = TQS-only control.
const ARM_META = {
  champion: { label: 'CHAMP', cls: 'text-amber-300', dot: 'text-amber-400' },
  unified_1a2a: { label: 'UNIFIED', cls: 'text-sky-300', dot: 'text-sky-400' },
  gate_off: { label: 'GATE-OFF', cls: 'text-violet-300', dot: 'text-violet-400' },
  regime_fit: { label: 'R-FIT', cls: 'text-teal-300', dot: 'text-teal-400' },
};
const ARM_ORDER = ['champion', 'unified_1a2a', 'gate_off', 'regime_fit'];

const _fmtPct = (v) => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${Number(v).toFixed(0)}%`;
};

const _fmtCount = (v) => {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return n.toLocaleString();
};

export const ShadowVsRealTile = () => {
  const [shadow, setShadow] = useState(null);
  const [real, setReal] = useState(null);
  const [arms, setArms] = useState(null);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      // Three independent fetches — partial data still renders.
      const [shadowRes, realRes, armRes] = await Promise.allSettled([
        api.get('/api/ai-modules/shadow/stats'),
        api.get('/api/trading-bot/stats/performance'),
        api.get('/api/slow-learning/shadow/arm-report?days=30'),
      ]);

      if (cancelled) return;

      let nextErr = null;

      if (shadowRes.status === 'fulfilled' && shadowRes.value?.data?.success) {
        setShadow(shadowRes.value.data.stats || {});
      } else {
        nextErr = 'shadow_unavailable';
      }

      if (realRes.status === 'fulfilled' && realRes.value?.data?.success) {
        setReal(realRes.value.data.stats || {});
      } else if (!nextErr) {
        nextErr = 'real_unavailable';
      }

      // Arm comparison is additive — its absence never sets the tile error.
      if (armRes.status === 'fulfilled' && armRes.value?.data?.success) {
        setArms(armRes.value.data.report || null);
      }

      setError(nextErr);
    };

    load();
    timerRef.current = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Loading state — both sources missing.
  if (!shadow && !real && !error) {
    return (
      <div
        data-testid="shadow-vs-real-loading"
        className="px-4 py-2 bg-zinc-950/40 text-xs text-zinc-500"
      >
        Shadow vs Real loading…
      </div>
    );
  }

  // Hard error — both endpoints unreachable. Hide silently rather
  // than dirty the V5 layout.
  if (error && !shadow && !real) {
    return null;
  }

  // Pull win-rates with sensible fallbacks.
  const shadowWr = shadow?.win_rate ?? null;            // Shadow tracker uses 0-100 scale
  const shadowTotal = shadow?.total_decisions ?? shadow?.total_logged ?? 0;
  const shadowExecuted = shadow?.executed_decisions ?? null;
  const shadowOnly = shadow?.shadow_only ?? null;
  const shadowOutcomes = shadow?.outcomes_tracked ?? 0;

  const realWr = real?.win_rate ?? null;                // /stats/performance is also 0-100
  const realTotal = real?.total_trades ?? 0;
  const realPnl = real?.total_pnl ?? null;

  // Compute divergence (shadow_wr - real_wr in percentage points).
  let divergence = null;
  let divergenceLabel = 'in sync';
  let DivergenceIcon = Minus;
  let divergenceClass = 'text-zinc-400';
  if (shadowWr !== null && realWr !== null && shadowOutcomes >= 5 && realTotal >= 5) {
    divergence = Number(shadowWr) - Number(realWr);
    if (divergence >= 5) {
      divergenceLabel = 'shadow ahead';
      DivergenceIcon = TrendingUp;
      divergenceClass = 'text-emerald-400';
    } else if (divergence <= -5) {
      divergenceLabel = 'shadow behind';
      DivergenceIcon = TrendingDown;
      divergenceClass = 'text-rose-400';
    } else {
      divergenceLabel = 'in sync';
      DivergenceIcon = Minus;
      divergenceClass = 'text-amber-400';
    }
  }

  // P3 Seam-3 — arm-comparison row (additive; renders only when arm data exists).
  const armRows = (arms?.arms || [])
    .filter((a) => a && a.signals > 0)
    .sort((a, b) => ARM_ORDER.indexOf(a.arm) - ARM_ORDER.indexOf(b.arm));

  return (
    <>
    <div
      data-testid="shadow-vs-real-tile"
      className="flex items-center gap-2 px-2 py-0.5 bg-zinc-950/40 border-t border-zinc-900 text-[14px] text-zinc-300 whitespace-nowrap overflow-hidden"
      title={
        // ── v19.34.25 (2026-05-06) — collapsed to a single line.
        // Pre-fix used a 2-column grid with 4 lines per column → forced
        // strip height to ~120px. Verbose breakdown (graded vs logged
        // vs exec vs watch-only counts) moved to this hover tooltip.
        [
          shadowOutcomes != null
            ? `Shadow: ${_fmtCount(shadowOutcomes)} graded · ${_fmtCount(shadowTotal)} logged${
                shadowExecuted !== null ? ` · ${_fmtCount(shadowExecuted)} exec` : ''
              }${shadowOnly !== null ? ` · ${_fmtCount(shadowOnly)} watch-only` : ''}`
            : null,
          realTotal != null ? `Real: ${_fmtCount(realTotal)} closed` : null,
        ].filter(Boolean).join(' | ')
      }
    >
      <Eye className="w-3 h-3 text-zinc-500 flex-shrink-0" />
      <span className="text-zinc-400 font-semibold uppercase tracking-wide text-[13px]">
        S vs R
      </span>
      {divergence !== null && (
        <span
          data-testid="shadow-vs-real-divergence"
          className={`flex items-center gap-0.5 ${divergenceClass}`}
        >
          <DivergenceIcon className="w-3 h-3" />
          <span className="font-mono text-[13px]">
            {divergence > 0 ? '+' : ''}{divergence.toFixed(0)}pp
          </span>
        </span>
      )}
      <span className="text-zinc-700">·</span>
      <span
        data-testid="shadow-vs-real-shadow-col"
        className="flex items-center gap-1 text-violet-300"
      >
        <span className="text-[13px] uppercase tracking-wide">Shadow</span>
        <span className="font-mono font-bold text-violet-200">
          {_fmtPct(shadowWr)}
        </span>
        <span className="text-zinc-500 text-[13px]">
          ({_fmtCount(shadowOutcomes)})
        </span>
      </span>
      <span className="text-zinc-700">·</span>
      <span
        data-testid="shadow-vs-real-real-col"
        className="flex items-center gap-1 text-emerald-300"
      >
        <Activity className="w-3 h-3" />
        <span className="text-[13px] uppercase tracking-wide">Real</span>
        <span className="font-mono font-bold text-emerald-200">
          {_fmtPct(realWr)}
        </span>
        <span className="text-zinc-500 text-[13px]">
          ({_fmtCount(realTotal)})
        </span>
        {realPnl !== null && (
          <span
            className={`font-mono text-[13px] ${
              realPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {realPnl >= 0 ? '+' : ''}${Number(realPnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        )}
      </span>
    </div>
    {armRows.length > 0 && (
      <div
        data-testid="shadow-arm-compare"
        className="flex items-center gap-2 px-2 py-0.5 bg-zinc-950/40 border-t border-zinc-900/60 text-[13px] text-zinc-300 whitespace-nowrap overflow-hidden"
        title="P3 shadow arms — champion (live dual-gate) vs unified_1a2a (single authority) vs gate_off (TQS-only). Win% over resolved · size-weighted R."
      >
        <GitBranch className="w-3 h-3 text-zinc-500 flex-shrink-0" />
        <span className="text-zinc-400 font-semibold uppercase tracking-wide text-[12px]">
          Arms
        </span>
        {armRows.map((a) => {
          const meta = ARM_META[a.arm] || { label: (a.arm || '?').toUpperCase(), cls: 'text-zinc-300', dot: 'text-zinc-400' };
          const wr = a.win_rate === null || a.win_rate === undefined ? '—' : `${Number(a.win_rate).toFixed(0)}%`;
          const wr8 = a.resolved > 0 ? wr : '—';
          const rW = a.weighted_r === null || a.weighted_r === undefined ? '—' : `${a.weighted_r >= 0 ? '+' : ''}${Number(a.weighted_r).toFixed(1)}R`;
          return (
            <span
              key={a.arm}
              data-testid={`shadow-arm-${a.arm}`}
              className={`flex items-center gap-1 ${meta.cls}`}
            >
              <span className={`text-[10px] ${meta.dot}`}>●</span>
              <span className="text-[12px] uppercase tracking-wide">{meta.label}</span>
              <span className="font-mono font-bold">{wr8}</span>
              <span className={`font-mono text-[12px] ${a.weighted_r >= 0 ? 'text-emerald-400/80' : 'text-rose-400/80'}`}>
                {rW}
              </span>
              <span className="text-zinc-600 text-[11px]">
                ({_fmtCount(a.resolved)}/{_fmtCount(a.signals)})
              </span>
            </span>
          );
        })}
      </div>
    )}
    </>
  );
};

export default ShadowVsRealTile;
