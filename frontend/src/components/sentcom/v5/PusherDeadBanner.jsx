/**
 * PusherDeadBanner — full-width loud alert at the top of V5 when the IB
 * pusher is dead during market hours. Visible EVERYWHERE; there is no way
 * to miss this. Silently hidden after-hours or when the pusher is fresh.
 *
 * This is the "loud failure mode" safety valve that replaces the old
 * silent Alpaca fallback. If the IB pusher dies, every consumer (scanner,
 * bot, chart) is already returning None/empty; this banner makes that
 * failure visible to the user so they can fix it (restart the Windows
 * pusher / IB Gateway) rather than watching degraded behaviour in silence.
 */
import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { usePusherHealth } from '../../../hooks/usePusherHealth';

const fmtAge = (sec) => {
  if (sec == null) return 'never';
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s ago`;
  return `${Math.floor(sec / 3600)}h ago`;
};

export const PusherDeadBanner = () => {
  const health = usePusherHealth();
  if (!health) return null;
  // Only loud when actually dead during market hours — stay quiet otherwise.
  if (!health.pusher_dead) return null;
  if (!health.in_market_hours) return null;

  return (
    <div
      data-testid="v5-pusher-dead-banner"
      className="w-full bg-rose-900/90 border-b-2 border-rose-500 text-rose-100 px-4 py-2 flex items-center justify-center gap-3 v5-mono text-xs font-semibold animate-pulse"
      style={{ zIndex: 59 }}
    >
      <AlertTriangle className="w-4 h-4 shrink-0 text-rose-300" />
      <span>
        IB PUSHER DEAD · last push {fmtAge(health.age_seconds)} · bot + scanner paused.
      </span>
      <span className="opacity-70">
        Restart the Windows pusher / IB Gateway to resume live trading.
      </span>
    </div>
  );
};

export default PusherDeadBanner;
