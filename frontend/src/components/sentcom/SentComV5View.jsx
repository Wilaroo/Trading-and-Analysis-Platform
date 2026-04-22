/**
 * SentComV5View — Stage 2d V5 Command-Center grid.
 *
 * Feature-flagged alternative layout for the full-page SentCom dashboard.
 * Activated with `?v5=1` in the URL. Falls back to the v4 layout otherwise.
 *
 * Layout contract (matches public/mockups/option-1-v5-command-center.html):
 *
 *   +-----------------------------------------------------------+
 *   | PipelineHUDV5  (Scan → Eval → Order → Manage → Close)     |
 *   +--------+---------------------------------------+----------+
 *   | 20%    | 55%                                   | 25%      |
 *   |        |                                       |          |
 *   | Scanner| ChartPanel (focused symbol)           | Model    |
 *   | · Live |                                       | Health   |
 *   | setups |                                       +----------+
 *   | alerts |                                       | Positions|
 *   |        |                                       +----------+
 *   |        |                                       | Stream + |
 *   |        |                                       | Chat     |
 *   +--------+---------------------------------------+----------+
 *
 * Non-goal: rebuild the mockup's scanner cards / chart bubbles from scratch.
 * We RE-USE the existing panels — this file is a pure composition layer, so
 * every hook, fetch, and underlying rendering path is untouched.
 */
import React from 'react';

import { GlassCard } from '../primitives/GlassCard';
import { ChartPanel } from './ChartPanel';
import { ModelHealthScorecard } from './ModelHealthScorecard';
import { PositionsPanel } from './PositionsPanel';
import { StreamPanel } from './StreamPanel';
import { ChatInput } from './ChatInput';
import { SetupsPanel } from './SetupsPanel';
import { AlertsPanel } from './AlertsPanel';
import { ContextPanel } from './ContextPanel';
import { PipelineHUDV5 } from './PipelineHUDV5';


/**
 * Derive pipeline-funnel counts from the hook state we already have.
 * Keeps domain logic localised so the view stays presentational.
 */
const derivePipelineCounts = ({ status, setups, positions, alerts, messages }) => {
  const pipeline = status?.order_pipeline || {};
  const openPositions = positions?.filter(p => p && (p.status !== 'closed')) || [];
  const todaysClosed = (messages || []).filter(m => {
    const kind = (m?.kind || m?.event || '').toLowerCase();
    return kind.includes('close') || kind.includes('filled') || kind.includes('win') || kind.includes('loss');
  }).length;

  return {
    scan: (setups?.length ?? 0),
    eval: (alerts?.length ?? 0),
    order: (pipeline.pending ?? 0) + (pipeline.executing ?? 0),
    manage: openPositions.length,
    close: todaysClosed,
  };
};


export const SentComV5View = ({
  // Status + context + positions + setups + alerts + messages
  status,
  context,
  positions,
  totalPnl,
  positionsLoading,
  setupsLoading,
  contextLoading,
  alertsLoading,
  setups,
  alerts,
  messages,
  streamLoading,
  // Handlers
  handleChat,
  setSelectedPosition,
  selectedPosition,
}) => {
  const counts = derivePipelineCounts({ status, setups, positions, alerts, messages });

  const equity = status?.account_equity ?? status?.equity ?? context?.account_equity;
  const latencySeconds = status?.order_latency_seconds ?? status?.latency_seconds;
  const phase = (status?.trading_phase || status?.phase || 'PAPER').toString().toUpperCase();

  const focusedSymbol =
    selectedPosition?.symbol
    || positions?.[0]?.symbol
    || 'SPY';

  return (
    <div
      data-testid="sentcom-v5-root"
      className="fixed inset-0 z-40 bg-zinc-950 text-white flex flex-col overflow-hidden"
    >
      {/* 1. Top-bar Pipeline HUD */}
      <PipelineHUDV5
        scanCount={counts.scan}
        scanSub={`${setups?.length ?? 0} setups · ${status?.active_timeframe || '5m'}`}
        evalCount={counts.eval}
        evalSub={alerts?.length ? `${alerts.length} alerts today` : 'no alerts'}
        orderCount={counts.order}
        orderSub={status?.order_pipeline?.pending != null
          ? `${status.order_pipeline.pending} pending · ${status.order_pipeline.executing ?? 0} exec`
          : undefined}
        manageCount={counts.manage}
        manageSub={positions?.length ? `${positions.length} open` : 'no positions'}
        manageAccent={totalPnl ? {
          color: totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400',
          text: `${totalPnl >= 0 ? '+' : '−'}$${Math.abs(totalPnl).toFixed(0)}`,
        } : undefined}
        closeCount={counts.close}
        closeSub={status?.daily_win_rate != null ? `WR ${Math.round(status.daily_win_rate * 100)}%` : undefined}
        totalPnl={totalPnl}
        equity={equity}
        latencySeconds={latencySeconds}
        phase={phase}
      />

      {/* 2. Main 3-col grid — 20% / 55% / 25% — fills remaining viewport */}
      <div
        data-testid="sentcom-v5-grid"
        className="grid gap-px bg-zinc-900 flex-1 min-h-0"
        style={{ gridTemplateColumns: '20% 55% 25%' }}
      >
        {/* LEFT — Scanner · Live */}
        <section
          data-testid="sentcom-v5-left"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
            <div className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">
              Scanner · Live
            </div>
            <div className="text-[9px] font-mono text-zinc-500">
              {(setups?.length ?? 0) + (alerts?.length ?? 0)} hits
            </div>
          </div>
          <div className="overflow-y-auto flex-1 p-2 space-y-2">
            <SetupsPanel
              setups={setups}
              loading={setupsLoading}
            />
            <AlertsPanel
              alerts={alerts}
              loading={alertsLoading}
            />
          </div>
        </section>

        {/* CENTER — Chart (primary visual surface) */}
        <section
          data-testid="sentcom-v5-center"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          <div className="flex-1 min-h-0 overflow-hidden">
            <ChartPanel
              symbol={focusedSymbol}
              initialTimeframe="5m"
              height={560}
            />
          </div>
          {/* Context strip under the chart — regime + session meta */}
          <div className="border-t border-zinc-800 max-h-[22vh] overflow-y-auto">
            <ContextPanel context={context} loading={contextLoading} />
          </div>
        </section>

        {/* RIGHT — stacked: Model Health · Positions · Stream+Chat */}
        <aside
          data-testid="sentcom-v5-right"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          {/* Model Health — compact, collapsed by default so it doesn't eat space */}
          <div className="border-b border-zinc-800 max-h-[28vh] overflow-y-auto">
            <ModelHealthScorecard className="rounded-none border-0" />
          </div>

          {/* Open positions */}
          <div className="border-b border-zinc-800 max-h-[28vh] overflow-y-auto">
            <PositionsPanel
              positions={positions}
              totalPnl={totalPnl}
              loading={positionsLoading}
              onSelectPosition={setSelectedPosition}
            />
          </div>

          {/* Unified stream + chat input anchored at the bottom */}
          <div className="flex-1 min-h-0 flex flex-col">
            <div className="flex-1 min-h-0 overflow-hidden">
              <StreamPanel messages={messages} loading={streamLoading} />
            </div>
            <div className="border-t border-zinc-800">
              <ChatInput onSend={handleChat} disabled={!status?.connected} />
            </div>
          </div>
        </aside>
      </div>

      {/* Corner watermark — makes the flag state unambiguous */}
      <div
        data-testid="sentcom-v5-badge"
        className="fixed bottom-1 right-2 text-[9px] font-mono text-zinc-600 pointer-events-none z-50"
      >
        v5 layout · <a href={typeof window !== 'undefined' ? window.location.pathname : '/'} className="text-violet-400 hover:underline pointer-events-auto">exit</a>
      </div>
    </div>
  );
};

export default SentComV5View;
