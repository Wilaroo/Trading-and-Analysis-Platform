/**
 * PipelineStageTile — V6 Plan A Phase A shared primitive.
 *
 * One Scan → Eval → Order → Manage → Close pipeline tile. Lifted verbatim out
 * of `panels/PipelineHUDV5.jsx` (was the private `Stage` sub-component) so the
 * V5 HUD and the V6 TopStrip pipeline pills render from ONE implementation.
 *
 * Honors the v19.34.110 ORDER-tile split contract (invariant #1): when
 * `splitCount = { queued, ibPending }` is supplied and `ibPending > 0`, the
 * tile renders `5q + 3@ib` instead of a flat count. Pair with the shared
 * `utils/orderPipelineSplit` helper that produces `splitCount`.
 *
 * Pure presentational — props in, JSX out. Zero behavior change.
 */
import React from 'react';

export const STAGE_COLOR = {
  scan:    { border: 'border-violet-900/60', bg: 'bg-violet-950/20', text: 'text-violet-400' },
  eval:    { border: 'border-blue-900/60',   bg: 'bg-blue-950/20',   text: 'text-blue-400' },
  order:   { border: 'border-amber-900/60',  bg: 'bg-amber-950/20',  text: 'text-amber-400' },
  manage:  { border: 'border-emerald-900/60',bg: 'bg-emerald-950/20',text: 'text-emerald-400' },
  close:   { border: 'border-slate-700',     bg: 'bg-slate-900/20',  text: 'text-slate-400' },
};

export const PipelineStageTile = ({ stage, label, count, sub, accent, splitCount, onClick, dataTestId }) => {
  const c = STAGE_COLOR[stage];
  const interactive = typeof onClick === 'function';
  // v19.34.110 — ORDER tile split. When `splitCount = { queued, ibPending }`
  // is provided and `ibPending > 0`, render `5q + 3@ib` instead of the
  // flat number. Lets the operator see at a glance how much work is
  // locally queued vs. how much is sitting at IB in `PendingSubmit`.
  const hasSplit = splitCount && (splitCount.ibPending ?? 0) > 0;
  return (
    <div
      data-testid={dataTestId || `v5-pipeline-stage-${stage}`}
      onClick={onClick}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={interactive ? (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick(e);
        }
      } : undefined}
      className={`flex-1 min-w-0 px-2 py-1.5 border rounded-sm ${c.border} ${c.bg} transition-colors hover:bg-white/5 v5-hud-block ${interactive ? 'cursor-pointer' : ''}`}
    >
      <div className="flex items-center justify-between gap-1.5">
        <span className={`text-[14px] uppercase tracking-[0.16em] font-bold ${c.text} truncate`}>{label}</span>
        <div className="flex items-baseline gap-1">
          {accent && (
            <span className={`v5-mono text-[14px] font-bold ${accent.color}`}>{accent.text}</span>
          )}
          {hasSplit ? (
            <span
              className="v5-mono text-xl font-bold text-zinc-100 leading-none whitespace-nowrap"
              data-testid={`${dataTestId || `v5-pipeline-stage-${stage}`}-split`}
              title={`${splitCount.queued ?? 0} queued locally · ${splitCount.ibPending ?? 0} awaiting IB terminal state`}
            >
              <span data-testid={`${dataTestId || `v5-pipeline-stage-${stage}`}-split-queued`}>{splitCount.queued ?? 0}</span>
              <span className="text-zinc-500 text-xs font-normal">q</span>
              <span className="text-zinc-500 text-sm px-0.5">+</span>
              <span className={c.text} data-testid={`${dataTestId || `v5-pipeline-stage-${stage}`}-split-ibpending`}>{splitCount.ibPending ?? 0}</span>
              <span className="text-zinc-500 text-xs font-normal">@ib</span>
            </span>
          ) : (
            <span className="v5-mono text-xl font-bold text-zinc-100 leading-none">{count ?? 0}</span>
          )}
        </div>
      </div>
      {sub && (
        <div className="text-[14px] text-zinc-500 truncate mt-0.5 v5-mono">{sub}</div>
      )}
    </div>
  );
};

export default PipelineStageTile;
