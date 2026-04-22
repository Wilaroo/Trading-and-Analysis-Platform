/**
 * SentComV5View — Stage 2d V5 Command-Center grid (primary layout).
 *
 *   +-----------------------------------------------------------+
 *   | PipelineHUDV5  (Scan → Eval → Order → Manage → Close)     |
 *   +--------+---------------------------------------+----------+
 *   | 20%    | 55%                                   | 25%      |
 *   | Scanner| ChartPanel + chart header             | Briefings|
 *   | Cards  |                                       +----------+
 *   |        |                                       | Open pos |
 *   |        |                                       +----------+
 *   |        |                                       | Stream + |
 *   |        |                                       | Chat     |
 *   +--------+---------------------------------------+----------+
 *
 * All V5 components live in `./v5/`. Existing panels are left untouched so
 * the `?v4=1` escape hatch keeps working. Zero backend changes.
 */
import React, { useState, useMemo } from 'react';

import { ChartPanel } from './panels/ChartPanel';
import { ModelHealthScorecard } from './panels/ModelHealthScorecard';
import { ChatInput } from './panels/ChatInput';
import { PipelineHUDV5 } from './panels/PipelineHUDV5';

import { useV5Styles } from './v5/useV5Styles';
import { ScannerCardsV5 } from './v5/ScannerCardsV5';
import { UnifiedStreamV5 } from './v5/UnifiedStreamV5';
import { BriefingsV5 } from './v5/BriefingsV5';
import { OpenPositionsV5 } from './v5/OpenPositionsV5';
import { useSafety, SafetyBannerV5, FlattenAllButtonV5, SafetyHudChip } from './v5/SafetyV5';


const derivePipelineCounts = ({ status, setups, positions, alerts, messages }) => {
  const pipeline = status?.order_pipeline || {};
  const openPositions = (positions || []).filter(p => p && p.status !== 'closed');
  const closedToday = (positions || []).filter(p => p?.status === 'closed');
  const streamCloses = (messages || []).filter(m => {
    const kind = (m?.event || m?.kind || '').toLowerCase();
    return kind.includes('close') || kind.includes('win') || kind.includes('loss');
  });

  // Aggregate eval quality
  const withGate = (alerts || []).filter(a => a?.gate_score != null);
  const gatePassCount = withGate.filter(a => a.gate_score >= 60).length;
  const avgGate = withGate.length
    ? Math.round(withGate.reduce((s, a) => s + Number(a.gate_score), 0) / withGate.length)
    : null;
  const gatePassPct = withGate.length
    ? Math.round((gatePassCount / withGate.length) * 100)
    : null;

  // Aggregate management
  const totalR = openPositions.reduce((s, p) => s + (Number(p.unrealized_r ?? p.pnl_r) || 0), 0);
  const stopsBreached = openPositions.filter(p => p.stop_breached || p.stop_hit).length;
  const openSymbols = openPositions.map(p => p.symbol).filter(Boolean).slice(0, 3).join(' · ');

  // Aggregate close
  const closedCount = closedToday.length || streamCloses.length;
  const winsCount = closedToday.filter(p => (p.realized_pnl ?? p.pnl ?? 0) > 0).length;
  const lossesCount = closedToday.filter(p => (p.realized_pnl ?? p.pnl ?? 0) < 0).length;
  const closedR = closedToday.reduce((s, p) => s + (Number(p.r_multiple) || 0), 0);
  const worstR = closedToday.length
    ? Math.min(...closedToday.map(p => Number(p.r_multiple) || 0))
    : null;
  const winRate = closedCount ? Math.round((winsCount / closedCount) * 100) : null;

  return {
    scan: (setups?.length ?? 0),
    scan_sub: status?.scanner_bar_size || status?.active_timeframe
      ? `${status.scanner_bar_size || status.active_timeframe}${status?.scanner_universe_size ? ` · ${status.scanner_universe_size} symbols` : ''}`
      : (setups?.length ? `${setups.length} setups` : '—'),
    eval: (alerts?.length ?? 0),
    eval_sub: withGate.length
      ? `${gatePassPct}% gate pass${avgGate != null ? ` · avg ${avgGate}` : ''}`
      : (alerts?.length ? `${alerts.length} alerts` : 'no alerts'),
    order: (pipeline.pending ?? 0) + (pipeline.executing ?? 0) + (pipeline.filled_today ?? 0),
    order_sub: pipeline.pending != null || pipeline.filled_today != null
      ? `${pipeline.filled_today ?? 0} filled · ${pipeline.pending ?? 0} pending${pipeline.last_ack_s != null ? ` · ${pipeline.last_ack_s}s` : ''}`
      : '—',
    manage: openPositions.length,
    manage_sub: openPositions.length > 0
      ? `${openSymbols || ''}${stopsBreached > 0 ? ` · ${stopsBreached} stops hit` : ' · no stops breached'}`
      : 'no positions',
    manage_r: openPositions.length ? totalR : null,
    close: closedCount,
    close_sub: closedCount > 0
      ? `WR ${winRate}%${closedR ? ` · $${closedR >= 0 ? '+' : '−'}${Math.abs(Math.round(closedR * 100))}` : ''}${worstR != null ? ` · worst ${worstR.toFixed(1)}R` : ''}`
      : 'no closes today',
    close_r: closedCount ? closedR : null,
    wins: winsCount,
    losses: lossesCount,
  };
};


export const SentComV5View = ({
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
  handleChat,
  selectedPosition,
  setSelectedPosition,
}) => {
  useV5Styles();
  const safety = useSafety();

  // Which scanner row is highlighted. Defaults to the first open position so
  // the chart is always meaningful on load.
  const [focusedSymbol, setFocusedSymbol] = useState(() =>
    selectedPosition?.symbol || positions?.[0]?.symbol || null
  );

  // Keep focus in sync when the external selectedPosition changes from
  // elsewhere in the app.
  const effectiveSymbol = useMemo(() => {
    return (
      focusedSymbol
      || selectedPosition?.symbol
      || positions?.[0]?.symbol
      || 'SPY'
    );
  }, [focusedSymbol, selectedPosition, positions]);

  const counts = derivePipelineCounts({ status, setups, positions, alerts, messages });

  const equity = status?.account_equity ?? status?.equity ?? context?.account_equity;
  const latencySeconds = status?.order_latency_seconds ?? status?.latency_seconds;
  const phase = (status?.trading_phase || status?.phase || 'PAPER').toString().toUpperCase();

  return (
    <div
      data-testid="sentcom-v5-root"
      className="fixed inset-0 z-40 bg-zinc-950 text-zinc-100 flex flex-col overflow-hidden v5-root"
    >
      {/* Safety kill-switch banner — z-60, above everything when tripped */}
      <SafetyBannerV5 safety={safety} />

      {/* 1. Top-bar Pipeline HUD */}
      <PipelineHUDV5
        scanCount={counts.scan}
        scanSub={counts.scan_sub}
        evalCount={counts.eval}
        evalSub={counts.eval_sub}
        orderCount={counts.order}
        orderSub={counts.order_sub}
        manageCount={counts.manage}
        manageSub={counts.manage_sub}
        manageAccent={counts.manage_r != null ? {
          color: counts.manage_r >= 0 ? 'text-emerald-400' : 'text-rose-400',
          text: `${counts.manage_r >= 0 ? '+' : ''}${counts.manage_r.toFixed(1)}R`,
        } : undefined}
        closeCount={counts.close}
        closeSub={counts.close_sub}
        closeAccent={counts.close_r != null ? {
          color: counts.close_r >= 0 ? 'text-emerald-400' : 'text-rose-400',
          text: `${counts.close_r >= 0 ? '+' : ''}${counts.close_r.toFixed(1)}R`,
        } : undefined}
        totalPnl={totalPnl}
        equity={equity}
        latencySeconds={latencySeconds}
        phase={phase}
        rightExtra={<SafetyHudChip safety={safety} />}
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
            <div className="v5-panel-title">Scanner · Live</div>
            <div className="text-[9px] v5-mono text-zinc-500">
              {(setups?.length ?? 0) + (alerts?.length ?? 0) + (positions?.length ?? 0)} hits
            </div>
          </div>
          <div className="overflow-y-auto flex-1 v5-scroll">
            <ScannerCardsV5
              setups={setups}
              alerts={alerts}
              positions={positions}
              messages={messages}
              selectedSymbol={effectiveSymbol}
              onSelectSymbol={setFocusedSymbol}
            />
          </div>
        </section>

        {/* CENTER — Chart (primary visual surface) */}
        <section
          data-testid="sentcom-v5-center"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          {/* Chart header strip — shows focused symbol + trade params */}
          <V5ChartHeader
            symbol={effectiveSymbol}
            position={positions?.find(p => p.symbol === effectiveSymbol)}
            focusedSymbolIsPosition={positions?.some(p => p.symbol === effectiveSymbol)}
          />

          <div className="flex-1 min-h-0 overflow-hidden">
            <ChartPanel
              symbol={effectiveSymbol}
              initialTimeframe="5m"
              height={600}
              position={positions?.find(p => p.symbol === effectiveSymbol) || null}
            />
          </div>
        </section>

        {/* RIGHT — stacked: Briefings · Open Positions · Stream+Chat */}
        <aside
          data-testid="sentcom-v5-right"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          {/* Briefings (~28vh) */}
          <div className="border-b border-zinc-800 flex flex-col" style={{ maxHeight: '28vh' }}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
              <div className="v5-panel-title">Briefings</div>
              <div className="text-[9px] v5-mono v5-dim">auto · 4 scheduled</div>
            </div>
            <div className="overflow-y-auto flex-1 v5-scroll">
              <BriefingsV5 context={context} positions={positions} totalPnl={totalPnl} />
            </div>
          </div>

          {/* Open positions (~24vh) */}
          <div className="border-b border-zinc-800 flex flex-col" style={{ maxHeight: '24vh' }}>
            <OpenPositionsV5
              positions={positions}
              totalPnl={totalPnl}
              loading={positionsLoading}
              onSelectPosition={(p) => {
                setSelectedPosition?.(p);
                setFocusedSymbol(p.symbol);
              }}
            />
          </div>

          {/* Stream + chat input anchored at the bottom */}
          <div className="flex-1 min-h-0 flex flex-col">
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
              <div className="v5-panel-title">Unified Stream</div>
              <span className="v5-chip v5-chip-manage">live</span>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto v5-scroll">
              <UnifiedStreamV5 messages={messages} loading={streamLoading} />
            </div>
            <div className="border-t border-zinc-800">
              <ChatInput onSend={handleChat} disabled={!status?.connected} />
            </div>
          </div>
        </aside>
      </div>

      {/* Model Health — still available, but in an unobtrusive drawer at the
          bottom so it doesn't steal space from the main grid. */}
      <div className="border-t border-zinc-800 max-h-[22vh] overflow-y-auto v5-scroll bg-zinc-950">
        <ModelHealthScorecard className="rounded-none border-0" />
      </div>

      {/* Emergency flatten-all button — bottom-left corner, z-55 */}
      <FlattenAllButtonV5 safety={safety} />

      {/* Corner watermark — lets users opt out to v4 */}
      <div
        data-testid="sentcom-v5-badge"
        className="fixed bottom-1 right-2 text-[9px] v5-mono text-zinc-600 pointer-events-none z-50"
      >
        v5 · <a
          href={typeof window !== 'undefined' ? `${window.location.pathname}?v4=1` : '/'}
          className="text-violet-400 hover:underline pointer-events-auto"
        >switch to v4</a>
      </div>
    </div>
  );
};


/** Header strip above the chart showing symbol + entry/SL/PT if position is open. */
const V5ChartHeader = ({ symbol, position, focusedSymbolIsPosition }) => {
  const dir = (position?.direction || position?.side || '').toLowerCase();
  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-3 min-w-0">
        <span className="v5-mono font-bold text-base text-zinc-100">{symbol}</span>
        {focusedSymbolIsPosition && (
          <span className={`v5-chip ${dir === 'short' ? 'v5-chip-veto' : 'v5-chip-manage'}`}>
            {dir === 'short' ? 'SHORT' : 'LONG'}{position?.setup_type ? ` · ${position.setup_type}` : ''}
          </span>
        )}
        {position && (
          <div className="flex items-center gap-2 pl-3 border-l border-zinc-800 text-[10px] v5-mono">
            {position.entry_price != null && (<><span className="v5-dim">E</span><span className="v5-warn font-bold">{Number(position.entry_price).toFixed(2)}</span></>)}
            {position.stop_price != null && (<><span className="v5-dim ml-1">SL</span><span className="v5-down font-bold">{Number(position.stop_price).toFixed(2)}</span></>)}
            {position.target_price != null && (<><span className="v5-dim ml-1">PT</span><span className="v5-up font-bold">{Number(position.target_price).toFixed(2)}</span></>)}
            {position.risk_reward != null && (<><span className="v5-dim ml-1">R:R</span><span className="font-bold text-zinc-200">{Number(position.risk_reward).toFixed(1)}</span></>)}
            {position.quantity != null && <span className="v5-dim ml-1">{position.quantity}sh</span>}
          </div>
        )}
      </div>
    </div>
  );
};


export default SentComV5View;
