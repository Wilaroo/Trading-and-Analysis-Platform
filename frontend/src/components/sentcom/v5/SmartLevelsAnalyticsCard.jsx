/**
 * SmartLevelsAnalyticsCard — A/B view of the liquidity-aware execution
 * layers (stop-guard, target-snap, VP-path multiplier).
 *
 * For each layer, shows two cohorts side-by-side: trades where the
 * snap/multiplier fired vs trades where it didn't. The operator can
 * tell at a glance whether a layer is moving live P&L:
 *   - mean R-multiple lift
 *   - win-rate lift
 *   - sample size (so they don't overweight low-N noise)
 *
 * Reads `/api/trading-bot/multiplier-analytics`. Refreshes on mount and
 * every 60s. Renders nothing until data arrives (avoids layout pop).
 */
import React, { useEffect, useState, useCallback } from 'react';
import { TrendingUp, TrendingDown, Activity, Target, Shield, Layers } from 'lucide-react';
import { safeGet } from '../../../utils/api';

const _fmtR = (r) => (r == null ? '—' : `${r >= 0 ? '+' : ''}${r.toFixed(2)}R`);
const _fmtPct = (p) => (p == null ? '—' : `${(p * 100).toFixed(0)}%`);
const _fmtPnl = (p) => {
  if (p == null) return '—';
  const sign = p >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(p).toFixed(0)}`;
};

const _liftClass = (firedV, notV) => {
  if (firedV == null || notV == null) return 'text-zinc-400';
  if (firedV > notV) return 'text-emerald-400';
  if (firedV < notV) return 'text-rose-400';
  return 'text-zinc-400';
};

const CohortRow = ({ label, summary, accent }) => (
  <div
    data-testid={`cohort-row-${label.toLowerCase().replace(/\s+/g, '-')}`}
    className="grid grid-cols-5 items-center gap-2 px-3 py-1.5 text-[13px]"
  >
    <span className={`v5-mono ${accent || 'text-zinc-300'}`}>{label}</span>
    <span className="v5-mono text-right text-zinc-400">{summary?.count ?? 0}</span>
    <span className="v5-mono text-right text-zinc-100">
      {_fmtR(summary?.mean_r)}
    </span>
    <span className="v5-mono text-right text-zinc-100">
      {_fmtPct(summary?.win_rate)}
    </span>
    <span className="v5-mono text-right text-zinc-100">
      {_fmtPnl(summary?.total_pnl)}
    </span>
  </div>
);

const LayerBlock = ({ icon: Icon, title, fired, notFired, firedLabel, notLabel }) => {
  const meanLift = (fired?.mean_r != null && notFired?.mean_r != null)
    ? fired.mean_r - notFired.mean_r
    : null;
  return (
    <div
      data-testid={`layer-block-${title.toLowerCase().replace(/\s+/g, '-')}`}
      className="border border-zinc-800/60 rounded-md bg-zinc-950/40"
    >
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-zinc-800/60 bg-zinc-900/40">
        <div className="flex items-center gap-2 text-zinc-200 text-xs uppercase tracking-wider">
          <Icon className="w-3.5 h-3.5 opacity-70" />
          <span>{title}</span>
        </div>
        <span
          className={`v5-mono text-[12px] ${_liftClass(fired?.mean_r, notFired?.mean_r)}`}
          title="Mean R-multiple lift between cohorts"
        >
          {meanLift == null ? '—' : `${meanLift >= 0 ? '+' : ''}${meanLift.toFixed(2)}R lift`}
        </span>
      </div>
      <div className="grid grid-cols-5 px-3 py-1 text-[12px] text-zinc-500 uppercase tracking-wider border-b border-zinc-900">
        <span>Cohort</span>
        <span className="text-right">N</span>
        <span className="text-right">Mean R</span>
        <span className="text-right">Win %</span>
        <span className="text-right">PnL</span>
      </div>
      <CohortRow label={firedLabel} summary={fired} accent="text-emerald-300" />
      <CohortRow label={notLabel}   summary={notFired} accent="text-zinc-400" />
    </div>
  );
};

export const SmartLevelsAnalyticsCard = ({ daysBack = 30, className = '' }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const resp = await safeGet(
        `/api/trading-bot/multiplier-analytics?days_back=${daysBack}&only_closed=true`,
        { timeout: 8000 },
      );
      setData(resp);
      setErr(null);
    } catch (e) {
      setErr(e?.message || 'load failed');
    } finally {
      setLoading(false);
    }
  }, [daysBack]);

  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, [load]);

  if (loading && !data) return null;
  if (err) {
    return (
      <div
        data-testid="smart-levels-analytics-error"
        className={`px-4 py-2 border border-zinc-800 rounded-md bg-zinc-950/40 text-xs text-zinc-500 ${className}`}
      >
        Smart-levels analytics unavailable: {err}
      </div>
    );
  }
  if (!data) return null;
  if ((data.total_trades || 0) === 0) {
    return (
      <div
        data-testid="smart-levels-analytics-empty"
        className={`px-4 py-2 border border-zinc-800 rounded-md bg-zinc-950/40 text-xs text-zinc-500 ${className}`}
      >
        Smart-levels analytics — no closed trades in the last {data.window_days}d yet.
      </div>
    );
  }

  return (
    <div
      data-testid="smart-levels-analytics-card"
      className={`border border-zinc-800/70 rounded-lg bg-zinc-950/50 ${className}`}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800/70">
        <div className="flex items-center gap-2 text-zinc-200 text-xs uppercase tracking-wider">
          <Layers className="w-4 h-4 opacity-70" />
          <span>Smart-levels analytics</span>
          <span className="text-[12px] text-zinc-500">
            ({data.total_trades} closed · {data.window_days}d)
          </span>
        </div>
        <button
          data-testid="smart-levels-analytics-refresh"
          onClick={load}
          className="text-[12px] text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          refresh
        </button>
      </div>
      <div className="p-3 grid gap-2">
        <LayerBlock
          icon={Shield}
          title="Stop-guard"
          fired={data.stop_guard?.fired}
          notFired={data.stop_guard?.not_fired}
          firedLabel="Widened"
          notLabel="Stayed"
        />
        <LayerBlock
          icon={Target}
          title="Target-snap"
          fired={data.target_snap?.fired}
          notFired={data.target_snap?.not_fired}
          firedLabel="Snapped"
          notLabel="Stayed"
        />
        <LayerBlock
          icon={Activity}
          title="VP-path multiplier"
          fired={data.vp_path?.downsized}
          notFired={data.vp_path?.full_size}
          firedLabel="Downsized"
          notLabel="Full size"
        />
      </div>
    </div>
  );
};

export default SmartLevelsAnalyticsCard;
