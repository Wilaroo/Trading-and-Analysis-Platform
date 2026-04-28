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
import React, { useCallback, useState, useMemo } from 'react';

import { ChartPanel } from './panels/ChartPanel';
import { ModelHealthScorecard } from './panels/ModelHealthScorecard';
import { ChatInput } from './panels/ChatInput';
import { PipelineHUDV5 } from './panels/PipelineHUDV5';

import { useV5Styles } from './v5/useV5Styles';
import { ScannerCardsV5 } from './v5/ScannerCardsV5';
import { TopMoversTile } from './v5/TopMoversTile';
import { UnifiedStreamV5 } from './v5/UnifiedStreamV5';
import { HealthChip } from './v5/HealthChip';
import { FreshnessInspector } from './v5/FreshnessInspector';
import { CommandPalette } from './v5/CommandPalette';
import { PanelErrorBoundary } from './v5/PanelErrorBoundary';
import { BriefingsV5 } from './v5/BriefingsV5';
import { OpenPositionsV5 } from './v5/OpenPositionsV5';
import { useSafety, SafetyBannerV5, FlattenAllButtonV5, SafetyHudChip, AwaitingQuotesPillV5, AccountGuardChipV5 } from './v5/SafetyV5';
import { PusherHealthChip } from './v5/PusherHealthChip';
import { PusherHeartbeatTile } from './v5/PusherHeartbeatTile';
import { StrategyMixCard } from './v5/StrategyMixCard';
import { DeadLetterBadge } from './v5/DeadLetterBadge';
import { ConnectivityCheck } from './v5/ConnectivityCheck';
import { PusherDeadBanner } from './v5/PusherDeadBanner';
import { LiveDataChip } from './v5/LiveDataChip';
import { CarouselCountdownChip } from './v5/CarouselCountdownChip';
import { useTickerModal } from '../../hooks/useTickerModal';
import {
  useMondayMorningAutoLoad,
  isoWeekFromBrowser,
  readPausedFlag,
  writePausedFlag,
} from '../../hooks/useMondayMorningAutoLoad';


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
    order: (pipeline.pending ?? 0) + (pipeline.executing ?? 0) + (pipeline.filled ?? pipeline.filled_today ?? 0),
    order_sub: (pipeline.pending != null || pipeline.filled != null || pipeline.filled_today != null)
      ? `${pipeline.filled ?? pipeline.filled_today ?? 0} filled · ${pipeline.pending ?? 0} pending${pipeline.last_ack_s != null ? ` · ${pipeline.last_ack_s}s ack` : ''}`
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
  onOpenBriefingDeepDive,
}) => {
  useV5Styles();
  const safety = useSafety();

  // Which scanner row is highlighted. Defaults to the first open position so
  // the chart is always meaningful on load.
  const [focusedSymbol, setFocusedSymbol] = useState(() =>
    selectedPosition?.symbol || positions?.[0]?.symbol || null
  );
  // Tracks whether the operator has clicked anything this session — used
  // by the Monday-morning auto-load hook so it never overrides an
  // explicit manual choice. State (not ref) so the carousel chip
  // re-renders into PAUSED mode the moment the operator takes over.
  // Seeded from localStorage so a page reload after an explicit
  // override doesn't silently re-enable the carousel before the
  // operator places their order.
  const [userHasFocused, setUserHasFocused] = useState(() => {
    const wid = isoWeekFromBrowser();
    return readPausedFlag(wid);
  });
  const setFocusedSymbolUserDriven = useCallback((sym) => {
    setUserHasFocused(true);
    const wid = isoWeekFromBrowser();
    if (wid) writePausedFlag(wid);
    setFocusedSymbol(sym);
  }, []);

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

  // Single entry point for every ticker-symbol click anywhere inside V5:
  //   1. focus the symbol on the center chart (preserves the old UX)
  //   2. open the EnhancedTickerModal for deep analysis
  // The modal's own data cache (3 min, per-symbol) keeps subsequent opens
  // of the same ticker near-instant, so spamming this is cheap.
  const { openTickerModal } = useTickerModal();
  const handleOpenTicker = useCallback((symbol) => {
    if (!symbol) return;
    const sym = String(symbol).toUpperCase();
    setFocusedSymbolUserDriven(sym);
    openTickerModal(sym);
  }, [openTickerModal, setFocusedSymbolUserDriven]);

  // Monday 09:25-09:40 ET — auto-frame the chart on the Weekend
  // Briefing's #1 watch. Idempotent per ISO week (localStorage flag).
  // Skipped entirely if the operator has already manually focused
  // anything since page load — explicit user choice always wins.
  useMondayMorningAutoLoad({
    setFocusedSymbol,
    userHasFocused,
  });

  // Phase 5 stability bundle — freshness inspector modal visibility.
  const [inspectorOpen, setInspectorOpen] = useState(false);

  return (
    <div
      data-testid="sentcom-v5-root"
      className="fixed top-0 right-0 bottom-0 left-[52px] z-30 bg-zinc-950 text-zinc-100 flex flex-col overflow-hidden v5-root"
    >
      {/* Safety kill-switch banner — z-60, above everything when tripped */}
      <SafetyBannerV5 safety={safety} />

      {/* Pusher DEAD banner — loud failure mode when IB pusher stops feeding
          during market hours. Everything downstream (scanner, bot, chart)
          is already returning empty/stale in that state; this banner makes
          it impossible to miss. Silent when fresh / after-hours. */}
      <PusherDeadBanner />

      {/* Awaiting-quotes pill — z-58, shown while the bot is waiting for IB quotes */}
      <AwaitingQuotesPillV5 safety={safety} />

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
        rightExtra={
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="cmdk-hint"
              data-help-id="cmd-k"
              title="Press ⌘K (Mac) or Ctrl+K to open the symbol search palette"
              onClick={() => window.dispatchEvent(new CustomEvent('sentcom:open-command-palette'))}
              className="hidden md:inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-zinc-800 bg-zinc-950 v5-mono text-[9px] text-zinc-500 uppercase tracking-wide select-none hover:border-violet-700 hover:text-violet-300 transition-colors"
            >
              <kbd className="font-bold text-zinc-400">⌘K</kbd>
              <span className="opacity-60">search</span>
            </button>
            <HealthChip onOpenInspector={() => setInspectorOpen(true)} />
            <ConnectivityCheck />
            <PusherHealthChip />
            <DeadLetterBadge />
            <FlattenAllButtonV5 safety={safety} inline />
            <AccountGuardChipV5 safety={safety} />
            <SafetyHudChip safety={safety} />
          </div>
        }
      />

      {/* Phase 5 stability bundle — global ⌘K palette + freshness inspector */}
      <CommandPalette onSelectSymbol={handleOpenTicker} />
      <FreshnessInspector
        isOpen={inspectorOpen}
        onClose={() => setInspectorOpen(false)}
      />

      {/* Phase 3 TopMoversTile + Pusher Heartbeat + Strategy Mix —
          collapsed into a single horizontal status strip 2026-04-28c
          to give the chart + Unified Stream more vertical real estate.
          Each tile renders without its own border-b; the wrapper
          carries the bottom border + dividers between tiles. On
          smaller widths the row wraps automatically (flex-wrap). */}
      <div
        data-testid="sentcom-v5-status-strip"
        className="flex items-stretch flex-wrap border-b border-zinc-800 divide-x divide-zinc-800"
      >
        <PanelErrorBoundary label="top-movers" compact>
          <TopMoversTile onSelectSymbol={handleOpenTicker} className="flex-1 min-w-[420px]" />
        </PanelErrorBoundary>
        <PanelErrorBoundary label="pusher-heartbeat" compact>
          <PusherHeartbeatTile />
        </PanelErrorBoundary>
        <PanelErrorBoundary label="strategy-mix" compact>
          <StrategyMixCard />
        </PanelErrorBoundary>
      </div>

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
            <div className="flex items-center gap-2">
              <div className="v5-panel-title">Scanner · Live</div>
              <LiveDataChip compact />
            </div>
            <div className="text-[9px] v5-mono text-zinc-500" data-testid="v5-scanner-hits-count">
              {(() => {
                // Count unique symbols across setups/alerts/positions so the
                // header matches the deduped card list below (a single
                // NVDA setup + NVDA alert collapses into 1 card, not 2).
                const syms = new Set();
                (setups || []).forEach(s => s?.symbol && syms.add(String(s.symbol).toUpperCase()));
                (alerts || []).forEach(a => a?.symbol && syms.add(String(a.symbol).toUpperCase()));
                (positions || []).forEach(p => p?.symbol && syms.add(String(p.symbol).toUpperCase()));
                const n = syms.size;
                return `${n} ${n === 1 ? 'hit' : 'hits'}`;
              })()}
            </div>
          </div>
          <div className="overflow-y-auto flex-1 v5-scroll">
            <PanelErrorBoundary label="scanner">
              <ScannerCardsV5
                setups={setups}
                alerts={alerts}
                positions={positions}
                messages={messages}
                selectedSymbol={effectiveSymbol}
                onSelectSymbol={handleOpenTicker}
              />
            </PanelErrorBoundary>
          </div>
        </section>

        {/* CENTER — Chart (top) + Unified Stream + chat (bottom).
            2026-04-28 layout move: stream pulled out of the right
            sidebar and given more horizontal real estate here. The
            right sidebar keeps the at-a-glance panels (briefings +
            positions); the wider stream is where the operator now
            reads the bot's narrative thoughts. */}
        <section
          data-testid="sentcom-v5-center"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          {/* Chart header strip — shows focused symbol + trade params */}
          <V5ChartHeader
            symbol={effectiveSymbol}
            position={positions?.find(p => p.symbol === effectiveSymbol)}
            focusedSymbolIsPosition={positions?.some(p => p.symbol === effectiveSymbol)}
            onSymbolClick={handleOpenTicker}
            onCarouselPick={setFocusedSymbolUserDriven}
            onChangeSymbol={setFocusedSymbolUserDriven}
            userHasFocused={userHasFocused}
          />

          {/* Chart (~60% of center). Container styling matters here:
              the inner ChartPanel has a ResizeObserver that re-fits
              the chart to the parent's actual height — so the parent
              MUST have a deterministic height (flex-basis + min-h-0
              + overflow-hidden) or the volume pane / x-axis ticks
              get clipped. */}
          <div
            className="min-h-0 overflow-hidden flex flex-col"
            style={{ flex: '60 1 0%' }}
          >
            <PanelErrorBoundary label="chart">
              <ChartPanel
                symbol={effectiveSymbol}
                initialTimeframe="5m"
                position={positions?.find(p => p.symbol === effectiveSymbol) || null}
              />
            </PanelErrorBoundary>
          </div>

          {/* Unified Stream + chat (~40% of center) — wider than the
              old right-sidebar location so bot narratives + rejection
              thoughts have room to breathe. */}
          <div
            data-testid="sentcom-v5-stream-center"
            className="border-t border-zinc-800 flex flex-col min-h-0 overflow-hidden"
            style={{ flex: '40 1 0%' }}
          >
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
              <div className="v5-panel-title">Unified Stream</div>
              <span className="v5-chip v5-chip-manage">live</span>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto v5-scroll">
              <UnifiedStreamV5 messages={messages} loading={streamLoading} onSymbolClick={handleOpenTicker} />
            </div>
            <div className="border-t border-zinc-800">
              {/* Chat is independent of IB Gateway — chat_server (port
                  8002) is always reachable. Previously this was tied
                  to status?.connected which falsely disabled chat
                  every weekend / overnight when IB was offline. */}
              <ChatInput onSend={handleChat} />
            </div>
          </div>
        </section>

        {/* RIGHT — stacked: Briefings · Open Positions (stream moved
            to center 2026-04-28) */}
        <aside
          data-testid="sentcom-v5-right"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          {/* Briefings (top half) */}
          <div className="border-b border-zinc-800 flex flex-col flex-1 min-h-0">
            <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
              <div className="v5-panel-title">Briefings</div>
              <div className="text-[9px] v5-mono v5-dim">auto · 4 scheduled</div>
            </div>
            <div className="overflow-y-auto flex-1 v5-scroll">
              <PanelErrorBoundary label="briefings">
                <BriefingsV5 context={context} positions={positions} totalPnl={totalPnl} onSymbolClick={handleOpenTicker} onOpenDeepDive={onOpenBriefingDeepDive} />
              </PanelErrorBoundary>
            </div>
          </div>

          {/* Open positions (bottom half) */}
          <div className="flex flex-col flex-1 min-h-0">
            <OpenPositionsV5
              positions={positions}
              totalPnl={totalPnl}
              loading={positionsLoading}
              onSelectPosition={(p) => {
                setSelectedPosition?.(p);
                handleOpenTicker(p.symbol);
              }}
            />
          </div>
        </aside>
      </div>

      {/* Model Health — still available, but in an unobtrusive drawer at the
          bottom so it doesn't steal space from the main grid. */}
      <div className="border-t border-zinc-800 max-h-[22vh] overflow-y-auto v5-scroll bg-zinc-950">
        <ModelHealthScorecard className="rounded-none border-0" />
      </div>

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
const V5ChartHeader = ({ symbol, position, focusedSymbolIsPosition, onSymbolClick, onChangeSymbol, onCarouselPick, userHasFocused }) => {
  const dir = (position?.direction || position?.side || '').toLowerCase();
  const [draft, setDraft] = useState('');
  const commit = useCallback(() => {
    const next = draft.trim().toUpperCase();
    if (!next || next === symbol) {
      setDraft('');
      return;
    }
    onChangeSymbol?.(next);
    setDraft('');
  }, [draft, symbol, onChangeSymbol]);
  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-3 min-w-0">
        {onSymbolClick ? (
          <button
            type="button"
            onClick={() => onSymbolClick(symbol)}
            className="v5-mono font-bold text-base text-zinc-100 hover:text-cyan-300 hover:underline transition-colors"
            data-testid={`chart-header-symbol-${symbol}`}
            title={`Open ${symbol} deep analysis`}
          >
            {symbol}
          </button>
        ) : (
          <span className="v5-mono font-bold text-base text-zinc-100">{symbol}</span>
        )}
        {onChangeSymbol && (
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); commit(); }
              if (e.key === 'Escape') { setDraft(''); e.currentTarget.blur(); }
            }}
            onBlur={commit}
            placeholder="type ticker ↵"
            maxLength={10}
            spellCheck={false}
            autoComplete="off"
            data-testid="chart-header-symbol-input"
            className="bg-transparent border border-zinc-800 focus:border-cyan-700 focus:outline-none rounded px-2 py-[2px] text-[11px] v5-mono uppercase tracking-wider w-28 placeholder-zinc-600 text-zinc-200"
          />
        )}
        <LiveDataChip />
        <CarouselCountdownChip
          onManualPick={onCarouselPick}
          userHasFocused={userHasFocused}
          currentChartSymbol={symbol}
        />
        {focusedSymbolIsPosition && (
          <span className={`v5-chip ${dir === 'short' ? 'v5-chip-veto' : 'v5-chip-manage'}`}>
            {dir === 'short' ? 'SHORT' : 'LONG'}{position?.setup_type ? ` · ${position.setup_type}` : ''}
          </span>
        )}
        {position && (
          <div className="flex items-center gap-2 pl-3 border-l border-zinc-800 text-[10px] v5-mono">
            {position.entry_price != null && (<><span className="v5-dim">E</span><span className="v5-warn font-bold">{Number(position.entry_price).toFixed(2)}</span></>)}
            {position.stop_price != null && (<><span className="v5-dim ml-1">SL</span><span className="v5-down font-bold">{Number(position.stop_price).toFixed(2)}</span></>)}
            {(() => {
              const pt = position.target_price ?? (Array.isArray(position.target_prices) ? position.target_prices[0] : null);
              return pt != null ? (<><span className="v5-dim ml-1">PT</span><span className="v5-up font-bold">{Number(pt).toFixed(2)}</span></>) : null;
            })()}
            {position.risk_reward != null && (<><span className="v5-dim ml-1">R:R</span><span className="font-bold text-zinc-200">{Number(position.risk_reward).toFixed(1)}</span></>)}
            {(() => {
              // Backend bot/IB positions provide `shares`; some legacy rows provide `quantity`.
              const q = position.shares ?? position.quantity;
              return q != null ? <span className="v5-dim ml-1">{q}sh</span> : null;
            })()}
          </div>
        )}
      </div>
    </div>
  );
};


export default SentComV5View;
