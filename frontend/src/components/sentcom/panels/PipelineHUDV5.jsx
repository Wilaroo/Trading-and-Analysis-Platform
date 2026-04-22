/**
 * PipelineHUDV5 — Stage 2d V5 top-bar pipeline funnel.
 *
 * Five-stage horizontal HUD: Scan → Evaluate → Order → Manage → Close Today,
 * plus a right-side metrics cluster (P&L / Equity / Latency / Phase).
 * Pure presentational component — consumer passes every count so we never
 * fetch here. Counts are derived upstream from the existing SentCom hooks.
 *
 * Matches the aesthetic of `public/mockups/option-1-v5-command-center.html`
 * without breaking any existing panels or styles.
 */
import React from 'react';

const stageColor = {
  scan:    { border: 'border-violet-900/60', bg: 'bg-violet-950/20', text: 'text-violet-400' },
  eval:    { border: 'border-blue-900/60',   bg: 'bg-blue-950/20',   text: 'text-blue-400' },
  order:   { border: 'border-amber-900/60',  bg: 'bg-amber-950/20',  text: 'text-amber-400' },
  manage:  { border: 'border-emerald-900/60',bg: 'bg-emerald-950/20',text: 'text-emerald-400' },
  close:   { border: 'border-slate-700',     bg: 'bg-slate-900/20',  text: 'text-slate-400' },
};

const Stage = ({ stage, label, count, sub, accent }) => {
  const c = stageColor[stage];
  return (
    <div
      data-testid={`v5-pipeline-stage-${stage}`}
      className={`flex-1 px-2.5 py-1.5 border rounded-sm ${c.border} ${c.bg} transition-colors hover:bg-white/5`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className={`text-[9px] uppercase tracking-widest font-semibold ${c.text}`}>{label}</span>
        <span className="font-mono text-lg font-bold text-zinc-100">{count ?? 0}</span>
        {accent && <span className={`font-mono text-[10px] ${accent.color}`}>{accent.text}</span>}
      </div>
      {sub && <div className="text-[9px] text-zinc-500 truncate">{sub}</div>}
    </div>
  );
};

const Metric = ({ label, value, color = 'text-zinc-100' }) => (
  <div className="text-right">
    <div className="text-[9px] uppercase tracking-widest text-zinc-500">{label}</div>
    <div className={`font-mono text-sm font-bold ${color}`}>{value}</div>
  </div>
);

const formatMoney = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '$—';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatEquity = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '$—';
  return `$${Math.round(Number(v)).toLocaleString('en-US')}`;
};

export const PipelineHUDV5 = ({
  scanCount = 0,
  scanSub,
  evalCount = 0,
  evalSub,
  orderCount = 0,
  orderSub,
  manageCount = 0,
  manageSub,
  manageAccent,
  closeCount = 0,
  closeSub,
  closeAccent,
  totalPnl = 0,
  equity,
  latencySeconds,
  phase = '—',
}) => {
  const pnlColor = (Number(totalPnl) || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400';
  const phaseColor =
    phase?.toUpperCase?.() === 'LIVE' ? 'text-emerald-400' :
    phase?.toUpperCase?.() === 'PAPER' ? 'text-amber-400' :
    'text-zinc-400';

  return (
    <div
      data-testid="v5-pipeline-hud"
      className="border-b border-zinc-800 bg-zinc-950 px-3 py-2"
    >
      <div className="flex items-center gap-2">
        <div className="text-[10px] font-mono text-zinc-500 pr-2 border-r border-zinc-800 font-semibold tracking-widest">
          SENTCOM
        </div>

        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <Stage stage="scan"   label="Scan"        count={scanCount}   sub={scanSub} />
          <span className="text-zinc-700 font-mono">→</span>
          <Stage stage="eval"   label="Evaluate"    count={evalCount}   sub={evalSub} />
          <span className="text-zinc-700 font-mono">→</span>
          <Stage stage="order"  label="Order"       count={orderCount}  sub={orderSub} />
          <span className="text-zinc-700 font-mono">→</span>
          <Stage stage="manage" label="Manage"      count={manageCount} sub={manageSub} accent={manageAccent} />
          <span className="text-zinc-700 font-mono">→</span>
          <Stage stage="close"  label="Close today" count={closeCount}  sub={closeSub}  accent={closeAccent} />
        </div>

        <div className="flex items-center gap-3 pl-3 border-l border-zinc-800 shrink-0">
          <Metric label="P&L"     value={formatMoney(totalPnl)}      color={pnlColor} />
          <Metric label="Equity"  value={formatEquity(equity)} />
          <Metric
            label="Latency"
            value={latencySeconds != null ? `${Number(latencySeconds).toFixed(1)}s` : '—'}
            color={latencySeconds != null && Number(latencySeconds) < 10 ? 'text-emerald-400' : 'text-amber-400'}
          />
          <Metric label="Phase"   value={phase}                      color={phaseColor} />
        </div>
      </div>
    </div>
  );
};

export default PipelineHUDV5;
