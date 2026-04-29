/**
 * Wave 3 (#7) — DayRollupBannerV5
 *
 * Sticky banner pinned at the top of Unified Stream summarising
 * today's trading-funnel state in one line:
 *
 *   `Today: 276 alerts · 20 HIGH · 16 eligible · 0 orders · driver: gate < 0.55 (88%)`
 *
 * Reads from /api/diagnostic/trade-funnel (existing endpoint, free).
 * Refreshes every 30s. Silently hides on error so a slow / down
 * diagnostic endpoint never breaks the stream.
 *
 * The "driver" line names the FIRST DEAD STAGE — the same diagnosis
 * the backend computes server-side. Operator sees the funnel state
 * without curling.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';

const POLL_INTERVAL_MS = 30000;

const _stageLabel = (stage) => {
  // Map raw stage keys to operator-facing labels.
  const map = {
    scanner_alerts: 'alerts',
    priority_high_or_critical: 'HIGH',
    tape_confirmed: 'tape',
    auto_execute_eligible: 'eligible',
    bot_trades_created: 'orders',
    broker_submitted: 'broker',
  };
  return map[stage] || stage;
};

export const DayRollupBannerV5 = ({ apiBase = '' }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchFunnel = useCallback(async () => {
    try {
      const r = await fetch(`${apiBase}/api/diagnostic/trade-funnel`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      if (!body?.success) throw new Error(body?.error || 'fetch failed');
      setData(body);
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => { fetchFunnel(); }, [fetchFunnel]);
  useEffect(() => {
    const id = setInterval(fetchFunnel, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchFunnel]);

  const summary = useMemo(() => {
    if (!data || !Array.isArray(data.stages)) return null;
    const get = (key) => data.stages.find((s) => s.stage === key)?.count;
    return {
      alerts: get('scanner_alerts') ?? 0,
      high: get('priority_high_or_critical') ?? 0,
      tape: get('tape_confirmed') ?? 0,
      eligible: get('auto_execute_eligible') ?? 0,
      orders: get('bot_trades_created') ?? 0,
      submitted: get('broker_submitted') ?? 0,
      first_dead: data.first_dead_stage,
      diagnosis: data.diagnosis,
    };
  }, [data]);

  // Hide silently on first-load failure so we don't show an empty
  // banner. Once we have data, errors keep the prior summary visible.
  if (loading || (!summary && error)) return null;
  if (!summary) return null;

  const ordersColor =
    summary.orders > 0 ? 'text-emerald-400' :
    summary.eligible > 0 ? 'text-rose-400' :  // had eligible alerts but 0 orders = something's killing trades
    'text-zinc-400';

  return (
    <div
      data-testid="v5-day-rollup-banner"
      className="px-3 py-1.5 border-b border-zinc-800 bg-zinc-900/40 sticky top-[33px] z-[9]"
      title={summary.diagnosis || 'Today\'s trading funnel'}
    >
      <div className="flex items-center justify-between gap-2 text-[12px] v5-mono">
        <div className="flex items-center gap-2 min-w-0 flex-wrap">
          <span className="text-zinc-500 uppercase tracking-widest text-[11px]">Today:</span>
          <Stat label="alerts" value={summary.alerts} />
          <Sep />
          <Stat label="HIGH" value={summary.high} color="text-blue-400" />
          <Sep />
          <Stat label="eligible" value={summary.eligible} color="text-amber-400" />
          <Sep />
          <Stat label="orders" value={summary.orders} color={ordersColor} bold />
        </div>
        {summary.first_dead && summary.orders === 0 && summary.alerts > 0 && (
          <span
            className="shrink-0 v5-mono text-[11px] text-zinc-500 truncate"
            title={summary.diagnosis}
          >
            killed at: <span className="text-rose-400 font-bold">{_stageLabel(summary.first_dead)}</span>
          </span>
        )}
      </div>
    </div>
  );
};

const Stat = ({ label, value, color = 'text-zinc-200', bold = false }) => (
  <span>
    <span className="text-zinc-500">{label} </span>
    <span className={`${color} ${bold ? 'font-bold' : 'font-semibold'}`}>{value}</span>
  </span>
);

const Sep = () => <span className="text-zinc-700">·</span>;

export default DayRollupBannerV5;
