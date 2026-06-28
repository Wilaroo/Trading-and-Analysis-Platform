/**
 * KpiRibbon — V6 Plan A composite (§4 5-col KPI row, §v110 micro-bar).
 *
 * The V6 cockpit's KPI ribbon: P&L · Equity · Open Risk · Throttle · RPC.
 * Composes the extracted Phase A primitives — `KpiMetric` + the v110
 * `OrderPipelineMicroBar` (under Open Risk) + the shared money formatters —
 * so V6 reuses the exact V5 rendering rather than reimplementing it.
 *
 * Pure presentational — props in, JSX out. The V6 shell (Phase B) feeds it
 * data from /api/sentcom/status; here it stays dumb and re-composable.
 *
 * Props:
 *   dayPnl      number   — realized+unrealized day P&L ($)
 *   equity      number   — account equity ($)
 *   openRisk    number   — aggregate open risk budget ($, abs)
 *   orderPipeline {pending, ib_pending, executing} — drives the micro-bar
 *   buyingPower number   — account buying power ($)
 *   buyingPowerColor string — tailwind text color for buying-power value
 *   rpc         string   — pusher/RPC freshness label (e.g. "2.1s", "STALE")
 *   rpcColor    string   — tailwind text color for rpc value
 */
import React from 'react';
import { KpiMetric, formatMoney, formatEquity } from './KpiMetric';
import { OrderPipelineMicroBar } from './OrderPipelineMicroBar';

export const KpiRibbon = ({
  dayPnl,
  equity,
  openRisk,
  orderPipeline,
  buyingPower,
  buyingPowerColor = 'text-zinc-100',
  rpc = '—',
  rpcColor = 'text-zinc-100',
  className = '',
}) => {
  const pnlColor = (dayPnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400';
  return (
    <div
      data-testid="v6-kpi-ribbon"
      className={`flex items-stretch justify-between gap-6 px-4 py-2 ${className}`.trim()}
    >
      <KpiMetric label="P&L" value={formatMoney(dayPnl)} color={pnlColor} />
      <KpiMetric label="Equity" value={formatEquity(equity)} />

      {/* Open Risk + v110 in-flight micro-bar adjunct */}
      <div className="text-right min-w-[88px]" data-testid="v6-kpi-open-risk">
        <div className="text-[14px] uppercase tracking-widest text-zinc-500">Open Risk</div>
        <div className="font-mono text-sm font-bold text-amber-300">{formatEquity(openRisk)}</div>
        <OrderPipelineMicroBar orderPipeline={orderPipeline} />
      </div>

      <KpiMetric label="Buying Power" value={formatEquity(buyingPower)} color={buyingPowerColor} />
      <KpiMetric label="RPC" value={rpc} color={rpcColor} />
    </div>
  );
};

export default KpiRibbon;
