/**
 * KpiMetric + money formatters — V6 Plan A Phase A shared primitives.
 *
 * Lifted verbatim out of `panels/PipelineHUDV5.jsx` (the private `Metric`
 * sub-component + `formatMoney` / `formatEquity`) so the V5 HUD metrics
 * cluster and the V6 KPI ribbon (P&L · Equity · Open Risk · Throttle · RPC)
 * render from ONE implementation.
 *
 * Pure presentational — props in, JSX out. Zero behavior change.
 */
import React from 'react';

export const KpiMetric = ({ label, value, color = 'text-zinc-100' }) => (
  <div className="text-right">
    <div className="text-[14px] uppercase tracking-widest text-zinc-500">{label}</div>
    <div className={`font-mono text-sm font-bold ${color}`}>{value}</div>
  </div>
);

export const formatMoney = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '$—';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export const formatEquity = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '$—';
  return `$${Math.round(Number(v)).toLocaleString('en-US')}`;
};

export default KpiMetric;
