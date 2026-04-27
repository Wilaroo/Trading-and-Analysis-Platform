/**
 * StrategyMixCard — surfaces silent biases in the scanner.
 *
 * Reads /api/scanner/strategy-mix — distribution of `setup_type` across
 * the last 100 alerts. If one strategy dominates (≥70% of alerts), shows
 * a concentration warning. STRONG_EDGE alerts are highlighted per bucket
 * so the operator can see "this strategy fires often AND the AI agrees".
 *
 * Why this matters: the scanner spent multiple sessions firing only
 * `relative_strength_leader` because of a data-staleness bug. A
 * concentration warning would have surfaced that within the first 20
 * alerts instead of letting it run for days unnoticed.
 */
import React, { useState, useEffect, useRef } from 'react';
import { AlertTriangle, BarChart3, Zap } from 'lucide-react';
import api from '../../../utils/api';

const POLL_INTERVAL_MS = 30_000;
const MAX_VISIBLE_BUCKETS = 8;

const PALETTE = [
  'bg-emerald-500/70',
  'bg-sky-500/70',
  'bg-violet-500/70',
  'bg-amber-500/70',
  'bg-rose-500/70',
  'bg-teal-500/70',
  'bg-fuchsia-500/70',
  'bg-orange-500/70',
];

export const StrategyMixCard = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.get('/api/scanner/strategy-mix?n=100');
        if (!cancelled) {
          setData(res.data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'failed');
      }
    };
    load();
    timerRef.current = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  if (error) {
    return (
      <div
        data-testid="strategy-mix-card-error"
        className="px-4 py-3 border-b border-zinc-800 bg-zinc-950/40 text-xs text-zinc-500"
      >
        Strategy mix unavailable
      </div>
    );
  }

  if (!data || !data.buckets) {
    return (
      <div
        data-testid="strategy-mix-card-loading"
        className="px-4 py-3 border-b border-zinc-800 bg-zinc-950/40 text-xs text-zinc-500"
      >
        Strategy mix loading…
      </div>
    );
  }

  if (data.total === 0) {
    return (
      <div
        data-testid="strategy-mix-card-empty"
        className="px-4 py-3 border-b border-zinc-800 bg-zinc-950/40"
      >
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <BarChart3 className="w-3.5 h-3.5" />
          <span>Strategy mix · waiting for first alerts</span>
        </div>
      </div>
    );
  }

  const visible = data.buckets.slice(0, MAX_VISIBLE_BUCKETS);
  const hidden = data.buckets.length - visible.length;

  return (
    <div
      data-testid="strategy-mix-card"
      className="px-4 py-3 border-b border-zinc-800 bg-zinc-950/40 space-y-2"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs">
          <BarChart3 className="w-3.5 h-3.5 text-zinc-500" />
          <span className="text-zinc-400 font-medium tracking-wider">
            STRATEGY MIX
          </span>
          <span className="text-zinc-600">·</span>
          <span className="text-zinc-500">last {data.total} alerts</span>
        </div>
        {data.concentration_warning && (
          <div
            data-testid="strategy-mix-concentration-warning"
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold tracking-wider bg-rose-500/15 text-rose-300 border border-rose-500/30"
          >
            <AlertTriangle className="w-3 h-3" />
            {data.top_strategy_pct.toFixed(0)}% CONCENTRATION
          </div>
        )}
      </div>

      <div className="space-y-1">
        {visible.map((b, i) => (
          <div
            key={b.setup_type}
            data-testid={`strategy-mix-bucket-${b.setup_type}`}
            className="flex items-center gap-2 text-xs"
          >
            <span className="w-32 truncate text-zinc-400">{b.label}</span>
            <div className="flex-1 h-2 rounded bg-zinc-900/80 overflow-hidden relative">
              <div
                className={`h-full ${PALETTE[i % PALETTE.length]} transition-all duration-500`}
                style={{ width: `${Math.min(100, b.pct)}%` }}
              />
            </div>
            <span className="w-10 text-right v5-mono font-bold text-zinc-200">
              {b.pct.toFixed(0)}%
            </span>
            <span className="w-8 text-right v5-mono text-zinc-500">
              {b.count}
            </span>
            {b.strong_edge_count > 0 && (
              <span
                className="flex items-center gap-0.5 text-[10px] text-fuchsia-300"
                data-testid={`strategy-mix-strong-edge-${b.setup_type}`}
              >
                <Zap className="w-3 h-3" />
                {b.strong_edge_count}
              </span>
            )}
          </div>
        ))}
        {hidden > 0 && (
          <div
            className="text-[10px] text-zinc-600 italic pl-32"
            data-testid="strategy-mix-hidden-count"
          >
            +{hidden} more strategies
          </div>
        )}
      </div>
    </div>
  );
};

export default StrategyMixCard;
