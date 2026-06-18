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
import { ClosedTodayDrilldown } from '../v5/ClosedTodayDrilldown';
import { BotEdgeChip } from '../v5/BotEdgeChip';
import { PipelineStageDrilldown } from '../v5/PipelineStageDrilldown';
import {
  scanStageConfig,
  evalStageConfig,
  orderStageConfig,
  manageStageConfig,
} from '../v5/pipelineStageColumns';

const stageColor = {
  scan:    { border: 'border-violet-900/60', bg: 'bg-violet-950/20', text: 'text-violet-400' },
  eval:    { border: 'border-blue-900/60',   bg: 'bg-blue-950/20',   text: 'text-blue-400' },
  order:   { border: 'border-amber-900/60',  bg: 'bg-amber-950/20',  text: 'text-amber-400' },
  manage:  { border: 'border-emerald-900/60',bg: 'bg-emerald-950/20',text: 'text-emerald-400' },
  close:   { border: 'border-slate-700',     bg: 'bg-slate-900/20',  text: 'text-slate-400' },
};

const Stage = ({ stage, label, count, sub, accent, splitCount, onClick, dataTestId }) => {
  const c = stageColor[stage];
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

const Metric = ({ label, value, color = 'text-zinc-100' }) => (
  <div className="text-right">
    <div className="text-[14px] uppercase tracking-widest text-zinc-500">{label}</div>
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
  orderSplit,
  orderSub,
  manageCount = 0,
  manageSub,
  manageAccent,
  closeCount = 0,
  closeSub,
  closeAccent,
  totalPnl = 0,
  totalUnrealizedPnl,
  totalRealizedPnl,
  totalPnlToday,
  // v19.34.27 — realized PnL bifurcation for the HUD tooltip.
  totalRealizedPnlSession,
  realizedPnlSyntheticCount,
  realizedPnlSyntheticSum,
  // v19.31.8 — drill-down props
  closedToday,
  winsToday,
  lossesToday,
  // v19.34.263 — Bot-Edge vs Adopted P&L split.
  botEdgePnlToday,
  adoptedPnlToday,
  botRealizedPnlToday,
  adoptedRealizedPnlToday,
  // v19.34.316 — Scale-out attribution. Realized $$ booked TODAY
  // against still-open positions (ladder scale-outs not yet fully
  // closed). Surfaces previously-invisible IB scale-out PnL.
  totalPartialRealizedToday,
  partialRealizedBySymbol,
  // v19.31.9 — additional stages
  scanRows,
  evalRows,
  orderRows,
  managePositions,
  scanMeta,
  evalMeta,
  orderMeta,
  manageMeta,
  onJumpToTrade,
  equity,
  buyingPower,
  phase = '—',
  rightExtra = null,
}) => {
  // v19.31.9 — single source of truth for which stage panel is open.
  // Only one open at a time so they don't visually stack.
  const [openStage, setOpenStage] = React.useState(null);
  const scanStageRef = React.useRef(null);
  const evalStageRef = React.useRef(null);
  const orderStageRef = React.useRef(null);
  const manageStageRef = React.useRef(null);
  const closeStageRef = React.useRef(null);
  const toggle = (stage) => setOpenStage(prev => (prev === stage ? null : stage));
  const close = () => setOpenStage(null);

  const scanCfg = scanStageConfig({ scanCount: scanCount });
  const evalCfg = evalStageConfig(evalMeta || {});
  const orderCfg = orderStageConfig(orderMeta || {});
  const manageCfg = manageStageConfig(manageMeta || {});
  // 2026-05-04 v19.31.7 — operator asked for realized PnL alongside
  // unrealized. The single "P&L" tile now shows the day total
  // (realized + unrealized) with realized/unrealized split underneath.
  // Falls back to legacy totalPnl when v19.31.7 fields are absent
  // (e.g., still on an old backend).
  const dayTotal = (totalPnlToday ?? null) != null
    ? Number(totalPnlToday)
    : Number(totalPnl) || 0;
  const realizedNum = totalRealizedPnl != null ? Number(totalRealizedPnl) : null;
  const unrealizedNum = totalUnrealizedPnl != null
    ? Number(totalUnrealizedPnl)
    : Number(totalPnl) || 0;
  const pnlColor = dayTotal >= 0 ? 'text-emerald-400' : 'text-rose-400';
  const realizedColor = realizedNum != null && realizedNum >= 0 ? 'text-emerald-400' : 'text-rose-400';
  const unrealizedColor = unrealizedNum >= 0 ? 'text-emerald-400' : 'text-rose-400';
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
            margin accounts without truncating.
            2026-05-01 v19.23 — tightened to basis-3/5 + flex-shrink on
            stages so the metrics cluster never gets clipped on smaller
            displays. Operator flagged the cluster overlapping HealthChip
            / ConnectivityCheck / FlattenAll on the V5 mockup review. */}
        <div className="flex items-center gap-1 basis-3/5 min-w-0 shrink">
          {/* v19.31.9 — every stage is a clickable drill-down anchor. */}
          <div ref={scanStageRef} className="flex-1 min-w-0 relative">
            <Stage
              stage="scan" label="Scan" count={scanCount} sub={scanSub}
              dataTestId="v5-pipeline-stage-scan"
              onClick={() => toggle('scan')}
            />
            <PipelineStageDrilldown
              open={openStage === 'scan'} onClose={close} anchorRef={scanStageRef}
              title={scanCfg.title} versionTag={scanCfg.versionTag}
              headerExtras={scanCfg.headerExtras} columns={scanCfg.columns}
              filters={scanCfg.filters}
              rows={scanRows || []} defaultSortKey={scanCfg.defaultSortKey}
              emptyText={scanCfg.emptyText} onRowClick={onJumpToTrade}
              testIdPrefix="scan-drilldown"
            />
          </div>
          <span className="text-zinc-700 font-mono shrink-0">→</span>
          <div ref={evalStageRef} className="flex-1 min-w-0 relative">
            <Stage
              stage="eval" label="Evaluate" count={evalCount} sub={evalSub}
              dataTestId="v5-pipeline-stage-eval"
              onClick={() => toggle('eval')}
            />
            <PipelineStageDrilldown
              open={openStage === 'eval'} onClose={close} anchorRef={evalStageRef}
              title={evalCfg.title} versionTag={evalCfg.versionTag}
              headerExtras={evalCfg.headerExtras} columns={evalCfg.columns}
              filters={evalCfg.filters}
              rows={evalRows || []} defaultSortKey={evalCfg.defaultSortKey}
              emptyText={evalCfg.emptyText} onRowClick={onJumpToTrade}
              testIdPrefix="eval-drilldown"
            />
          </div>
          <span className="text-zinc-700 font-mono shrink-0">→</span>
          <div ref={orderStageRef} className="flex-1 min-w-0 relative">
            <Stage
              stage="order" label="Order" count={orderCount} sub={orderSub} splitCount={orderSplit}
              dataTestId="v5-pipeline-stage-order"
              onClick={() => toggle('order')}
            />
            <PipelineStageDrilldown
              open={openStage === 'order'} onClose={close} anchorRef={orderStageRef}
              title={orderCfg.title} versionTag={orderCfg.versionTag}
              headerExtras={orderCfg.headerExtras} columns={orderCfg.columns}
              filters={orderCfg.filters}
              rows={orderRows || []} defaultSortKey={orderCfg.defaultSortKey}
              emptyText={orderCfg.emptyText} onRowClick={onJumpToTrade}
              testIdPrefix="order-drilldown"
            />
          </div>
          <span className="text-zinc-700 font-mono shrink-0">→</span>
          <div ref={manageStageRef} className="flex-1 min-w-0 relative">
            <Stage
              stage="manage" label="Manage" count={manageCount} sub={manageSub} accent={manageAccent}
              dataTestId="v5-pipeline-stage-manage"
              onClick={() => toggle('manage')}
            />
            <PipelineStageDrilldown
              open={openStage === 'manage'} onClose={close} anchorRef={manageStageRef}
              title={manageCfg.title} versionTag={manageCfg.versionTag}
              headerExtras={manageCfg.headerExtras} columns={manageCfg.columns}
              filters={manageCfg.filters}
              rows={managePositions || []} defaultSortKey={manageCfg.defaultSortKey}
              emptyText={manageCfg.emptyText} onRowClick={onJumpToTrade}
              testIdPrefix="manage-drilldown"
            />
          </div>
          <span className="text-zinc-700 font-mono shrink-0">→</span>
          <div ref={closeStageRef} className="flex-1 min-w-0 relative">
            <Stage
              stage="close" label="Close today" count={closeCount} sub={closeSub} accent={closeAccent}
              dataTestId="v5-pipeline-stage-close"
              onClick={() => toggle('close')}
            />
            <ClosedTodayDrilldown
              open={openStage === 'close'} onClose={close}
              closedToday={closedToday} totalRealized={totalRealizedPnl ?? 0}
              winsToday={winsToday ?? 0} lossesToday={lossesToday ?? 0}
              anchorRef={closeStageRef} onJumpToTrade={onJumpToTrade}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 pl-3 border-l border-zinc-800 basis-2/5 min-w-0 shrink-0">
          {rightExtra}
          {/* v19.31.7 — Day P&L tile = realized + unrealized, with the
              split rendered underneath. When realized data is unavailable
              (legacy backend), falls back to single-line legacy display. */}
          {realizedNum != null ? (
            <div
              data-testid="pipeline-pnl-block"
              data-help-id="pipeline-pnl"
              className="flex flex-col items-end leading-tight"
              title={
                /* v19.34.27 — Bifurcated tooltip. The `R` value in the
                   chip is "today only, matches IB" (synthetic
                   reconciler-stamped closures excluded). The tooltip
                   surfaces the session-bookings figure + a
                   per-passenger count so the operator can audit why
                   the two might differ. */
                `Day P&L: ${formatMoney(dayTotal)}\n` +
                `  R (today, matches IB):   ${formatMoney(realizedNum)}\n` +
                `  U (unrealized):          ${formatMoney(unrealizedNum)}\n` +
                (realizedPnlSyntheticCount > 0
                  ? (
                      `\nSession bookings (incl. reconciler-stamped closures):\n` +
                      `  R-session:               ${formatMoney(totalRealizedPnlSession ?? realizedNum)}\n` +
                      `  + ${realizedPnlSyntheticCount} passenger closeout(s) totaling ` +
                      `${formatMoney(realizedPnlSyntheticSum ?? 0)}\n` +
                      `    (excluded from today R — IB realized these in prior sessions)`
                    )
                  : ``)
              }
            >
              <div className="flex items-baseline gap-1">
                <span className="text-[12px] uppercase tracking-wider text-zinc-500">P&L</span>
                <span data-testid="pipeline-pnl-day" className={`v5-mono text-[13px] font-semibold ${pnlColor}`}>
                  {formatMoney(dayTotal)}
                </span>
              </div>
              <div className="flex items-baseline gap-2 text-[13px] v5-mono">
                <span
                  data-testid="pipeline-pnl-realized"
                  data-realized-session={totalRealizedPnlSession ?? realizedNum}
                  data-synthetic-count={realizedPnlSyntheticCount ?? 0}
                  className={realizedColor}
                >
                  R {formatMoney(realizedNum)}
                  {/* v19.34.27 — small ° glyph appears when there ARE
                      synthetic closures excluded from R-today. Signals
                      to the operator: "I'm not just summing everything;
                      hover for the breakdown." Subtle on purpose so it
                      doesn't compete with the dollar value. */}
                  {realizedPnlSyntheticCount > 0 && (
                    <span className="text-zinc-500 ml-0.5" aria-hidden>°</span>
                  )}
                </span>
                <span data-testid="pipeline-pnl-unrealized" className={unrealizedColor}>
                  U {formatMoney(unrealizedNum)}
                </span>
                {/* v19.34.316 — Scale-out (S) chip. Real $$ booked TODAY
                    against open positions via ladder scale-outs. Hidden
                    when zero so the chip doesn't get noisy. Tooltip lists
                    every contributing symbol. */}
                {Number(totalPartialRealizedToday || 0) !== 0 && (
                  <span
                    data-testid="pipeline-pnl-scaleout"
                    className={Number(totalPartialRealizedToday) >= 0 ? 'text-emerald-400' : 'text-rose-400'}
                    title={
                      `Scale-outs today (open positions, ladder fills):\n` +
                      `  S total: ${formatMoney(Number(totalPartialRealizedToday))}\n\n` +
                      `Per-symbol:\n` +
                      (partialRealizedBySymbol && Object.keys(partialRealizedBySymbol).length
                        ? Object.entries(partialRealizedBySymbol)
                            .filter(([, v]) => v && Number(v.realized || 0) !== 0)
                            .sort((a, b) => Math.abs(Number(b[1].realized || 0)) - Math.abs(Number(a[1].realized || 0)))
                            .map(([s, v]) => `  ${s}: ${formatMoney(Number(v.realized || 0))} (${v.shares_closed || 0} sh / ${v.fills || 0} fills)`)
                            .join('\n')
                        : '  (none)')
                    }
                  >
                    S {formatMoney(Number(totalPartialRealizedToday))}
                  </span>
                )}
              </div>
              {/* v19.34.58 — Inline synthetic-bookings line.
                  Pre-v19.34.58 the synthetic-closeout context lived ONLY
                  in the title="" tooltip. Operator review 2026-05-20:
                  with R=$0.00° and 11 synthetic closeouts totaling
                  -$2,507, the chip read as "nothing happened today" at
                  a glance — the ° glyph wasn\'t loud enough to overcome
                  the dominant zero. This line surfaces the synthetic
                  count + session sum directly under the R/U split when
                  count > 0, so the synthetic loss is visible without a
                  hover. Same data as the tooltip, just promoted. */}
              {realizedPnlSyntheticCount > 0 && (
                <div
                  data-testid="pipeline-pnl-synthetic-line"
                  className="flex items-baseline gap-1 text-[11px] v5-mono text-zinc-500"
                  title="Synthetic closeouts: bot records that IB had already realized in prior sessions. Excluded from today R to avoid double-counting against IB\'s books."
                >
                  <span>+{realizedPnlSyntheticCount} synthetic</span>
                  <span className="text-zinc-700">·</span>
                  <span
                    className={
                      (totalRealizedPnlSession ?? realizedPnlSyntheticSum ?? 0) >= 0
                        ? 'text-emerald-500/80'
                        : 'text-rose-500/80'
                    }
                  >
                    session {formatMoney(totalRealizedPnlSession ?? realizedPnlSyntheticSum ?? 0)}
                  </span>
                </div>
              )}
              {/* v19.34.263 — Bot-Edge vs Adopted split (backend v19.34.262).
                  Shows the bot's CLEAN edge separate from human-adopted /
                  reconciled positions so adopted P&L can't inflate the
                  headline bot performance. */}
              <BotEdgeChip
                botEdgePnlToday={botEdgePnlToday}
                adoptedPnlToday={adoptedPnlToday}
                botRealizedPnlToday={botRealizedPnlToday}
                adoptedRealizedPnlToday={adoptedRealizedPnlToday}
              />
            </div>
          ) : (
            <Metric label="P&L" value={formatMoney(totalPnl)} color={pnlColor} />
          )}
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
