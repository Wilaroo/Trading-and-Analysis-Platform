/**
 * PortfolioHealthPill — compact V5 status-strip indicator showing
 * whether IB Gateway's `updatePortfolio()` is actually delivering
 * full per-position payloads (marketPrice / unrealizedPNL / avgCost).
 *
 * Distinct from <PusherHeartbeatTile />, which surfaces pipeline
 * cadence. This pill surfaces payload QUALITY — the specific failure
 * mode that produced the v19.34.150 audit warning
 * `21/21 IB position(s) had unrealizedPNL=0`.
 *
 * Colors:
 *   green  → all live positions fully populated
 *   amber  → partial / market-price-only / slow heartbeat
 *   red    → reqAccountUpdates dead, avgCost dead, or stale push
 *   unknown→ no pushes ever / pusher disconnected
 *
 * Hover reveals the full diagnosis[] list + ghost count.
 *
 * 2026-02-13 v19.34.150b
 */
import React from 'react';
import { Activity } from 'lucide-react';
import { usePortfolioHealth } from '../../../hooks/usePortfolioHealth';

const COLOR = {
  green: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  red: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  unknown: 'bg-zinc-700/30 text-zinc-400 border-zinc-700/50',
};

const LABEL = {
  green: 'PORTFOLIO OK',
  amber: 'PORTFOLIO DEGRADED',
  red: 'PORTFOLIO DEAD',
  unknown: 'PORTFOLIO ?',
};

export const PortfolioHealthPill = () => {
  const data = usePortfolioHealth();
  if (!data) return null;

  const health = data.health || 'unknown';
  const klass = COLOR[health] || COLOR.unknown;
  const label = LABEL[health] || LABEL.unknown;

  const live = data.live_position_count ?? 0;
  const ghost = data.ghost_zero_position_count ?? 0;
  const diagnosis = Array.isArray(data.diagnosis) ? data.diagnosis : [];

  // Build a compact hover tooltip with the diagnosis lines + counts.
  const tooltip = [
    `Live: ${live}  Ghost (closed intraday): ${ghost}`,
    diagnosis.length > 0 ? '── diagnosis ──' : null,
    ...diagnosis,
  ].filter(Boolean).join('\n');

  return (
    <div
      data-testid="portfolio-health-pill"
      className="flex items-center gap-2 px-3 py-1 bg-zinc-950/60 text-[14px] leading-none whitespace-nowrap"
      title={tooltip}
    >
      <Activity className="w-3 h-3 text-zinc-500" />
      <span
        data-testid="portfolio-health-pill-label"
        className={`px-1.5 py-0.5 rounded text-[13px] font-bold tracking-wider border ${klass}`}
      >
        {label}
      </span>
      <span className="text-zinc-500 v5-mono">
        <span data-testid="portfolio-health-live-count" className="text-zinc-200 font-bold">
          {live}
        </span>
        <span> live</span>
        {ghost > 0 && (
          <>
            <span className="text-zinc-700"> · </span>
            <span
              data-testid="portfolio-health-ghost-count"
              className="text-zinc-500"
              title="Zero-quantity IB Gateway snapshot artifacts (closed intraday). Reset on next session."
            >
              {ghost} 👻
            </span>
          </>
        )}
      </span>
    </div>
  );
};

export default PortfolioHealthPill;
