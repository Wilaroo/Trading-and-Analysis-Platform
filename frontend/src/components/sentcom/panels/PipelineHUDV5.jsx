/**
 * PipelineHUDV5 — Stage 2d V5 top-bar pipeline funnel.
 *
 * Five-stage horizontal HUD: Scan → Evaluate → Order → Manage → Close Today,
 * plus a right-side metrics cluster (P&L / Equity / Buying Power / Phase).
 * Pure presentational component — consumer passes every count so we never
 * fetch here. Counts are derived upstream from the existing SentCom hooks.
 *
 * 2026-04-30 v19.6 — `Latency` metric replaced with `Buying Power` per
 * operator request. Buying power is the more actionable number on a
 * margin account (shows real-time margin headroom alongside equity);
 * latency is exposed in the Pusher Heartbeat tile already.
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
      className={`flex-1 min-w-0 px-3 py-2 border rounded-sm ${c.border} ${c.bg} transition-colors hover:bg-white/5 v5-hud-block`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={`text-[12px] uppercase tracking-[0.18em] font-bold ${c.text}`}>{label}</span>
        <div className="flex items-baseline gap-1.5">
          {accent && (
            <span className={`v5-mono text-[12px] font-bold ${accent.color}`}>{accent.text}</span>
          )}
          <span className="v5-mono text-2xl font-bold text-zinc-100 leading-none">{count ?? 0}</span>
        </div>
      </div>
      {sub && (
        <div className="text-[12px] text-zinc-500 truncate mt-0.5 v5-mono">{sub}</div>
      )}
    </div>
  );
};

const Metric = ({ label, value, color = 'text-zinc-100' }) => (
  <div className="text-right">
    <div className="text-[11px] uppercase tracking-widest text-zinc-500">{label}</div>
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
  buyingPower,
  phase = '—',
  rightExtra = null,
}) => {
  const pnlColor = (Number(totalPnl) || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400';
  const phaseColor =
    phase?.toUpperCase?.() === 'LIVE' ? 'text-emerald-400' :
    phase?.toUpperCase?.() === 'PAPER' ? 'text-amber-400' :
    'text-zinc-400';

  return (
    <div
      data-testid="v5-pipeline-hud"
      data-help-id="pipeline-hud"
      className="border-b border-zinc-800 bg-zinc-950 px-3 py-2"
    >
      <div className="flex items-center gap-2">
        <div className="text-[12px] font-mono text-zinc-500 pr-2 border-r border-zinc-800 font-semibold tracking-widest">
          SENTCOM
        </div>

        {/* 2026-04-30 v19.7 — stages constrained to ~2/3 width so the
            right-side metrics cluster (P&L / Equity / Buying Pwr / Phase)
            gets enough room to display 7-figure dollar values fully on
            margin accounts without truncating. */}
        <div className="flex items-center gap-1.5 basis-2/3 min-w-0">
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

        <div className="flex items-center justify-end gap-3 pl-3 border-l border-zinc-800 basis-1/3 min-w-0">
          {rightExtra}
          <Metric label="P&L"     value={formatMoney(totalPnl)}      color={pnlColor} />
          <Metric label="Equity"  value={formatEquity(equity)} />
          <Metric label="Buying Pwr"
            value={formatEquity(buyingPower)}
            color={
              buyingPower != null && equity != null && Number(buyingPower) > Number(equity) * 0.5
                ? 'text-emerald-400'
                : 'text-amber-400'
            }
          />
          <span data-help-id="pipeline-phase">
            <Metric label="Phase" value={phase} color={phaseColor} />
          </span>
        </div>
      </div>
    </div>
  );
};

export default PipelineHUDV5;
