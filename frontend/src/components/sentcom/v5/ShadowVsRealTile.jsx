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
import { Eye, Activity, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import api from '../../../utils/api';

const POLL_INTERVAL_MS = 60_000;

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
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      // Two independent fetches — partial data still renders.
      const [shadowRes, realRes] = await Promise.allSettled([
        api.get('/api/ai-modules/shadow/stats'),
        api.get('/api/trading-bot/stats/performance'),
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

  return (
    <div
      data-testid="shadow-vs-real-tile"
      className="flex items-center gap-2 px-2 py-0.5 bg-zinc-950/40 border-t border-zinc-900 text-[11px] text-zinc-300 whitespace-nowrap overflow-hidden"
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
      <span className="text-zinc-400 font-semibold uppercase tracking-wide text-[10px]">
        S vs R
      </span>
      {divergence !== null && (
        <span
          data-testid="shadow-vs-real-divergence"
          className={`flex items-center gap-0.5 ${divergenceClass}`}
        >
          <DivergenceIcon className="w-3 h-3" />
          <span className="font-mono text-[10px]">
            {divergence > 0 ? '+' : ''}{divergence.toFixed(0)}pp
          </span>
        </span>
      )}
      <span className="text-zinc-700">·</span>
      <span
        data-testid="shadow-vs-real-shadow-col"
        className="flex items-center gap-1 text-violet-300"
      >
        <span className="text-[10px] uppercase tracking-wide">Shadow</span>
        <span className="font-mono font-bold text-violet-200">
          {_fmtPct(shadowWr)}
        </span>
        <span className="text-zinc-500 text-[10px]">
          ({_fmtCount(shadowOutcomes)})
        </span>
      </span>
      <span className="text-zinc-700">·</span>
      <span
        data-testid="shadow-vs-real-real-col"
        className="flex items-center gap-1 text-emerald-300"
      >
        <Activity className="w-3 h-3" />
        <span className="text-[10px] uppercase tracking-wide">Real</span>
        <span className="font-mono font-bold text-emerald-200">
          {_fmtPct(realWr)}
        </span>
        <span className="text-zinc-500 text-[10px]">
          ({_fmtCount(realTotal)})
        </span>
        {realPnl !== null && (
          <span
            className={`font-mono text-[10px] ${
              realPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {realPnl >= 0 ? '+' : ''}${Number(realPnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        )}
      </span>
    </div>
  );
};

export default ShadowVsRealTile;
