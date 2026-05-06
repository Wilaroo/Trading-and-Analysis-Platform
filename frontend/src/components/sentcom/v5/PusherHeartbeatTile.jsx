/**
 * PusherHeartbeatTile — Positive proof-of-life for the IB pusher pipeline.
 *
 * Most of the V5 surface only tells you the pusher is broken (red banner,
 * stale chip). This tile flips that around — it shows the pusher's
 * pushes/min and RPC latency in real time so degradation shows up BEFORE
 * the dead threshold trips.
 *
 * Reads from the shared `usePusherHealth()` hook — no extra polling.
 *
 * Fields surfaced:
 *   • Animated pulse dot, colored by `health`
 *   • Last push age ("2.3s ago")
 *   • Pushes/min (last 60s rolling)
 *   • RPC latency: avg + p95 + last
 *   • Quote / position counts (already on the chip — kept here for
 *     glanceability)
 *
 * If the backend hasn't been updated yet (heartbeat block missing), the
 * tile gracefully degrades to "—" placeholders without errors.
 */
import React from 'react';
import { Activity, Zap, Clock, Send, BarChart3 } from 'lucide-react';
import { usePusherHealth } from '../../../hooks/usePusherHealth';

// Color tokens — keep in lock-step with PusherHealthChip mapping.
const HEALTH_COLOR = {
  green: { dot: 'bg-emerald-400', ring: 'shadow-emerald-500/30', text: 'text-emerald-300' },
  amber: { dot: 'bg-amber-400', ring: 'shadow-amber-500/30', text: 'text-amber-300' },
  red: { dot: 'bg-rose-500', ring: 'shadow-rose-500/30', text: 'text-rose-300' },
  unknown: { dot: 'bg-zinc-500', ring: 'shadow-zinc-500/20', text: 'text-zinc-400' },
};

const fmtAge = (sec) => {
  if (sec == null) return '—';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h`;
};

const fmtLat = (ms) => (ms == null ? '—' : `${Math.round(ms)}ms`);

const RATE_LABEL = {
  healthy: 'healthy',
  degraded: 'slowing',
  stalled: 'stalled',
  no_pushes: 'no pushes',
};

export const PusherHeartbeatTile = () => {
  const data = usePusherHealth();
  if (!data) return null;

  const palette = HEALTH_COLOR[data.health] || HEALTH_COLOR.unknown;
  const hb = data.heartbeat || {};
  const pushesPerMin = hb.pushes_per_min ?? null;
  const rateHealth = hb.push_rate_health || (data.health === 'unknown' ? 'no_pushes' : null);
  const rpcAvg = hb.rpc_latency_ms_avg ?? null;
  const rpcP95 = hb.rpc_latency_ms_p95 ?? null;
  const rpcLast = hb.rpc_latency_ms_last ?? null;
  const rpcSamples = hb.rpc_sample_size ?? 0;
  const totalPushes = hb.push_count_total ?? null;

  // Pulse animation: only run when we're actually getting pushes — a
  // dead pusher shouldn't have a "live" pulse.
  const pulse = data.health === 'green' && pushesPerMin > 0;

  return (
    <div
      data-testid="pusher-heartbeat-tile"
      className="flex items-center gap-2 px-2 py-0.5 bg-zinc-950/60 text-[11px] leading-none whitespace-nowrap overflow-hidden"
    >
      {/* ── v19.34.25 (2026-05-06) — collapsed to a single horizontal line.
          Pre-fix used flex-col for status+age stack + 4 separate flex
          rows (rate, RPC, total, counts) → forced strip height to ~80px.
          Now all 1 line, verbose secondary stats moved to `title` tooltip
          (hover the tile to see p95, avg, sample size, total counter,
          L2 symbols). */}
      <span className="relative flex h-2 w-2 flex-shrink-0">
        {pulse && (
          <span
            className={`absolute inline-flex h-full w-full rounded-full ${palette.dot} opacity-75 animate-ping`}
          />
        )}
        <span
          className={`relative inline-flex h-2 w-2 rounded-full ${palette.dot} shadow-md ${palette.ring}`}
          data-testid="pusher-heartbeat-pulse"
        />
      </span>
      <span className={`text-[10px] font-bold tracking-wider ${palette.text}`}>
        PUSHER {data.health?.toUpperCase() || '—'}
      </span>
      <span className="text-zinc-500 v5-mono">
        {fmtAge(data.age_seconds)} ago
      </span>
      <span className="text-zinc-700">·</span>
      <span
        data-testid="pusher-heartbeat-rate"
        className="flex items-center gap-1"
        title={
          totalPushes != null
            ? `Total pushes since boot: ${totalPushes.toLocaleString()}`
            : undefined
        }
      >
        <Send className="w-3 h-3 text-zinc-500" />
        <span className="font-bold text-zinc-200 v5-mono">{pushesPerMin ?? '—'}</span>
        <span className="text-zinc-500">/min</span>
        {rateHealth && rateHealth !== 'healthy' && pushesPerMin != null && (
          <span
            className={`ml-1 px-1 py-0 rounded text-[10px] font-bold tracking-wider ${
              rateHealth === 'degraded'
                ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                : 'bg-rose-500/15 text-rose-300 border border-rose-500/30'
            }`}
          >
            {RATE_LABEL[rateHealth]}
          </span>
        )}
      </span>
      <span className="text-zinc-700">·</span>
      <span
        data-testid="pusher-heartbeat-rpc"
        className="flex items-center gap-1"
        title={
          [
            rpcLast != null ? `last ${fmtLat(rpcLast)}` : null,
            rpcP95 != null ? `p95 ${fmtLat(rpcP95)}` : null,
            rpcAvg != null ? `avg ${fmtLat(rpcAvg)}` : null,
            rpcSamples > 0 ? `n=${rpcSamples}` : null,
          ].filter(Boolean).join(' · ') || undefined
        }
      >
        <Zap className="w-3 h-3 text-zinc-500" />
        <span className="text-zinc-500">RPC</span>
        <span className="font-bold text-zinc-200 v5-mono">{fmtLat(rpcLast)}</span>
      </span>
      <span className="text-zinc-700">·</span>
      <span
        data-testid="pusher-heartbeat-counts"
        className="flex items-center gap-1"
        title={
          data.counts?.level2_symbols > 0
            ? `${data.counts.level2_symbols} L2 symbols`
            : undefined
        }
      >
        <Activity className="w-3 h-3 text-zinc-500" />
        <span className="font-bold text-zinc-200 v5-mono">
          {data.counts?.quotes ?? 0}
        </span>
        <span className="text-zinc-500">q</span>
        <span className="text-zinc-700">·</span>
        <span className="font-bold text-zinc-200 v5-mono">
          {data.counts?.positions ?? 0}
        </span>
        <span className="text-zinc-500">pos</span>
      </span>
      {data.pusher_dead && (
        <span
          className="flex items-center gap-1 text-[10px] text-rose-300/80 ml-1"
          data-testid="pusher-heartbeat-dead-hint"
        >
          <Clock className="w-3 h-3" />
          paused
        </span>
      )}
    </div>
  );
};

export default PusherHeartbeatTile;
