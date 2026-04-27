/**
 * MarketStateBanner — top-of-modal hint surfaced inside FreshnessInspector
 * (and reusable anywhere the operator should know "buffers are active").
 *
 * Reads the canonical `/api/market-state` endpoint (single source of truth,
 * shared with live_bar_cache TTLs, backfill_readiness, account_guard,
 * enhanced_scanner). When `buffers_active` is true (weekend / overnight)
 * we render an amber banner so the operator understands at a glance why
 * staleness warnings look softer than usual.
 *
 * Stays silent during RTH + extended hours — no banner = market is doing
 * its normal thing.
 */
import React from 'react';
import { Moon, Coffee } from 'lucide-react';
import { useMarketState } from '../../../hooks/useMarketState';

const BANNER_BY_STATE = {
  weekend: {
    icon: Coffee,
    accent: 'border-amber-700/60 bg-amber-900/20 text-amber-200',
    iconColor: 'text-amber-300',
    title: 'Weekend Mode',
    detail: 'Stale-data buffers extended · IB offline · live subs frozen',
  },
  overnight: {
    icon: Moon,
    accent: 'border-indigo-700/60 bg-indigo-900/20 text-indigo-200',
    iconColor: 'text-indigo-300',
    title: 'Overnight',
    detail: 'Stale-data buffers extended · pre-market opens at 04:00 ET',
  },
};

export const MarketStateBanner = () => {
  // Shared hook — same source as the SENTCOM wordmark moon and the
  // DataFreshnessBadge chip moon. Single round-trip means all three
  // surfaces flip in lock-step on state boundaries.
  const snap = useMarketState();

  if (!snap || !snap.buffers_active) return null;
  const cfg = BANNER_BY_STATE[snap.state];
  if (!cfg) return null;
  const Icon = cfg.icon;

  // ET 12-hr clock for human-friendly display.
  let etClock = '';
  try {
    const d = new Date(snap.now_et);
    etClock = d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch { /* ignore */ }

  return (
    <div
      data-testid="market-state-banner"
      className={`flex items-center gap-3 px-3 py-2 rounded-md border ${cfg.accent}`}
    >
      <Icon className={`w-4 h-4 shrink-0 ${cfg.iconColor}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 v5-mono text-[10px] uppercase tracking-wider">
          <span className="font-bold">{cfg.title}</span>
          <span className="opacity-50">·</span>
          <span className="opacity-80">buffers active</span>
        </div>
        <div className="v5-mono text-[10px] opacity-80 truncate mt-0.5">
          {cfg.detail}
        </div>
      </div>
      {etClock && (
        <div
          data-testid="market-state-banner-clock"
          className="v5-mono text-[10px] opacity-70 tabular-nums whitespace-nowrap"
          title={`${snap.label} · ET wall clock`}
        >
          {etClock} ET
        </div>
      )}
    </div>
  );
};

export default MarketStateBanner;
