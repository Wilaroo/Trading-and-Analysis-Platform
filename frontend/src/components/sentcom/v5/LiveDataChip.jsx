/**
 * LiveDataChip — tiny reusable "LIVE · 2s" / "STALE · 3m" / "DEAD" badge.
 *
 * Drop-in on any panel that displays market data so the user always sees
 * whether what they're looking at is real-time (IB pusher fresh), delayed
 * (pusher slow), or dead (pusher not pushing — data is frozen).
 *
 * Reads from the shared usePusherHealth hook; no extra network calls.
 */
import React from 'react';
import { usePusherHealth } from '../../../hooks/usePusherHealth';

const fmtAge = (sec) => {
  if (sec == null) return '—';
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${Math.floor(sec / 3600)}h`;
};

const STATE_FROM_HEALTH = {
  green: { label: 'LIVE', cls: 'text-emerald-400 border-emerald-400/30 bg-emerald-500/10', dot: 'bg-emerald-400 animate-pulse' },
  amber: { label: 'SLOW', cls: 'text-amber-400 border-amber-400/30 bg-amber-500/10', dot: 'bg-amber-400' },
  red:   { label: 'DEAD', cls: 'text-rose-400 border-rose-400/30 bg-rose-500/10', dot: 'bg-rose-400' },
  unknown: { label: '—', cls: 'text-zinc-500 border-zinc-700 bg-zinc-900', dot: 'bg-zinc-600' },
};

export const LiveDataChip = ({ compact = false, className = '' }) => {
  const health = usePusherHealth();
  if (!health) return null;

  const state = STATE_FROM_HEALTH[health.health] || STATE_FROM_HEALTH.unknown;
  const age = fmtAge(health.age_seconds);

  return (
    <span
      data-testid="live-data-chip"
      data-help-id="live-data-chip"
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] v5-mono uppercase tracking-wider ${state.cls} ${className}`}
      title={`Pusher ${state.label} · last push ${age} ago`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${state.dot}`} />
      {!compact && <span>{state.label}</span>}
      {state.label !== 'DEAD' && state.label !== '—' && (
        <span className="opacity-70">· {age}</span>
      )}
    </span>
  );
};

export default LiveDataChip;
