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
import React, { useCallback, useRef, useState, useMemo } from 'react';

import { ChartPanel } from './panels/ChartPanel';
import { ChatInput } from './panels/ChatInput';
import { PipelineHUDV5 } from './panels/PipelineHUDV5';

import { useV5Styles } from './v5/useV5Styles';
import { ScannerCardsV5 } from './v5/ScannerCardsV5';
import { TopMoversTile } from './v5/TopMoversTile';
import { UnifiedStreamV5 } from './v5/UnifiedStreamV5';
import { DeepFeedV5 } from './v5/DeepFeedV5';
import { DayRollupBannerV5 } from './v5/DayRollupBannerV5';
import { EodCountdownBannerV5 } from './v5/EodCountdownBannerV5';
import { HealthChip } from './v5/HealthChip';
import { FreshnessInspector } from './v5/FreshnessInspector';
import { CommandPalette } from './v5/CommandPalette';
import { PanelErrorBoundary } from './v5/PanelErrorBoundary';
import { BriefingsCompactStrip } from './v5/BriefingsCompactStrip';
import { OpenPositionsV5 } from './v5/OpenPositionsV5';
import MLFeatureAuditPanel from './v5/MLFeatureAuditPanel';
import CpuReliefBadge from './v5/CpuReliefBadge';
import { useSafety, SafetyBannerV5, FlattenAllButtonV5, SafetyHudChip, AwaitingQuotesPillV5, AccountGuardChipV5 } from './v5/SafetyV5';
import { PusherHealthChip } from './v5/PusherHealthChip';
import { PusherHeartbeatTile } from './v5/PusherHeartbeatTile';
import { StrategyMixCard } from './v5/StrategyMixCard';
import { ShadowVsRealTile } from './v5/ShadowVsRealTile';
import { DrawerSplitHandle, useDrawerSplit } from './v5/DrawerSplitHandle';
import SentComIntelligencePanel from '../NIA/SentComIntelligencePanel';
import { DeadLetterBadge } from './v5/DeadLetterBadge';
import { ConnectivityCheck } from './v5/ConnectivityCheck';
import { PusherDeadBanner } from './v5/PusherDeadBanner';
// v19.30.11 (2026-05-01) — high-priority system alerts (pusher dead 30s+,
// mongo down, etc.) with explicit operator action guidance. Goes ABOVE
// PusherDeadBanner because it's broader (covers all critical subsystems
// not just pusher) and has the "DO NOT restart Spark backend" message
// that prevented today's footgun.
import SystemBanner from './v5/SystemBanner';
// v19.31.13 (2026-05-04) — Account-mode badge in HUD top strip.
// Reads /api/system/account-mode every 30s. Big enough to never
// confuse PAPER (amber) for LIVE (red) when switching IB accounts.
import AccountModeBadge from './v5/AccountModeBadge';
// v19.31.14 (2026-05-04) — Boot-reconcile status pill. Self-hides
// after 10 min, only renders when AUTO_RECONCILE_AT_BOOT ran.
import BootReconcilePill from './v5/BootReconcilePill';
import { LiveDataChip } from './v5/LiveDataChip';
import { CarouselCountdownChip } from './v5/CarouselCountdownChip';
import { useTickerModal } from '../../hooks/useTickerModal';
import {
  useMondayMorningAutoLoad,
  isoWeekFromBrowser,
  readPausedFlag,
  writePausedFlag,
} from '../../hooks/useMondayMorningAutoLoad';


const derivePipelineCounts = ({ status, setups, positions, alerts, messages, closedToday, winsToday, lossesToday }) => {
  const pipeline = status?.order_pipeline || {};
  const openPositions = (positions || []).filter(p => p && p.status !== 'closed');
  // 2026-05-04 v19.31.7 — operator's CLOSE TODAY tile read 0 even when
  // the bot demonstrably closed positions today. Root cause: the
  // backend's /api/sentcom/positions endpoint returned only OPEN
  // positions (so filtering for `status === 'closed'` against that
  // array could never match anything). Now the backend returns a
  // dedicated `closed_today: [...]` array surfaced as the
  // `closedToday` prop. Stream-message fallback is kept for cases
  // where the backend list is briefly stale post-close.
  const closedFromBackend = Array.isArray(closedToday) ? closedToday : [];
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

  // Aggregate close — v19.31.7 prefers the backend list, falls back
  // to filtering the positions array (legacy), and finally to the
  // stream-event scan.
  const positionsClosedFallback = (positions || []).filter(p => p?.status === 'closed');
  const closedSource = closedFromBackend.length > 0
    ? closedFromBackend
    : positionsClosedFallback;
  const closedCount = closedSource.length || streamCloses.length;
  const wins = winsToday ?? closedSource.filter(p => (p.realized_pnl ?? p.pnl ?? 0) > 0).length;
  const losses = lossesToday ?? closedSource.filter(p => (p.realized_pnl ?? p.pnl ?? 0) < 0).length;
  const closedR = closedSource.reduce((s, p) => s + (Number(p.r_multiple) || 0), 0);
  const worstR = closedSource.length
    ? Math.min(...closedSource.map(p => Number(p.r_multiple) || 0))
    : null;
  const winRate = closedCount ? Math.round((wins / closedCount) * 100) : null;

  return {
    // 2026-04-30 v15 — operator flagged "SCAN 0 / EVAL 5" mismatch.
    // Root cause: `setups` came from the deprecated predictive_scanner
    // and is empty. The HUD's intent for SCAN is "what the live scanner
    // produced this cycle"; that's what `alerts` actually represents
    // post-deprecation. Falling back to alerts.length keeps the tile
    // honest until predictive_scanner is fully retired.
    scan: (setups?.length ?? 0) > 0 ? setups.length : (alerts?.length ?? 0),
    scan_sub: status?.scanner_bar_size || status?.active_timeframe
      ? `${status.scanner_bar_size || status.active_timeframe}${status?.scanner_universe_size ? ` · ${status.scanner_universe_size} symbols` : ''}`
      : (setups?.length ? `${setups.length} setups` : (alerts?.length ? `${alerts.length} alerts` : '—')),
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
    wins,
    losses,
    // v19.31.9 — drill-down rows + per-stage meta
    drilldown: {
      scan: alerts || [],
      eval: (alerts || []).filter(a => a?.gate_score != null || a?.combined_recommendation),
      // ORDER drill-down rebuilds from open positions + closed-today
      // entries — these carry the bot's actual fill records. Pending
      // orders aren't currently in /api/sentcom/positions, so we
      // surface filled fills only (the operator's "Order" tile counts
      // both pending+filled but the row list shows what we have).
      order: [
        ...openPositions.map(p => ({
          ...p,
          status: 'filled',
          fill_price: p.entry_price,
          placed_at: p.entry_time || p.executed_at,
          order_type: 'bracket',
        })),
        ...(closedFromBackend || []).map(c => ({
          ...c,
          status: 'filled',
          fill_price: c.entry_price,
          placed_at: c.executed_at,
          order_type: 'bracket',
        })),
      ],
      manage: openPositions,
      // close already handled by ClosedTodayDrilldown via closedToday prop
    },
    drilldownMeta: {
      scan: { scanCount: (alerts?.length ?? 0) },
      eval: { avgGate, gatePassPct },
      order: {
        filledCount: pipeline.filled ?? pipeline.filled_today ?? openPositions.length,
        pendingCount: pipeline.pending ?? 0,
      },
      manage: { totalUnrealized: openPositions.reduce((s, p) => s + (Number(p.pnl) || 0), 0), sumR: totalR },
    },
  };
};


export const SentComV5View = ({
  status,
  context,
  positions,
  totalPnl,
  totalUnrealizedPnl,
  totalRealizedPnl,
  totalPnlToday,
  closedToday,
  winsToday,
  lossesToday,
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

  const counts = derivePipelineCounts({
    status,
    setups,
    positions,
    alerts,
    messages,
    closedToday,
    winsToday,
    lossesToday,
  });

  // Bottom-drawer split state — operator-resizable via DrawerSplitHandle.
  // Persisted to localStorage so the chosen split survives refresh.
  const drawerContainerRef = useRef(null);
  const { leftPct, setLeftPct, resetToDefault } = useDrawerSplit();

  const equity = status?.account_equity ?? status?.equity ?? context?.account_equity;
  const buyingPower = status?.account_buying_power ?? status?.buying_power ?? context?.account_buying_power;
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

  // Wave-1 (#11) — cross-panel hover: hovering a row in either Stream
  // panel pulses the matching Scanner card. Single source of truth so
  // both Stream renderers + Scanner share the same `hoveredSymbol`.
  const [hoveredSymbol, setHoveredSymbol] = useState(null);
  const handleHoverSymbol = useCallback((sym) => {
    setHoveredSymbol(sym ? String(sym).toUpperCase() : null);
  }, []);

  // 2026-04-30 v19.10 — Scanner scroll-position tracker. The Scanner
  // panel's header shows "X / N hits" so the operator always knows
  // which card they're looking at as the list grows long. Updated by
  // <ScannerCardsV5/> via the `onScanProgress` callback (RAF-throttled).
  const [scanProgress, setScanProgress] = useState({ topIdx: 0, total: 0 });

  return (
    <div
      data-testid="sentcom-v5-root"
      // v19.34.1 (2026-05-04) — was `overflow-y-auto`, which let the
      // whole page scroll when inner panels grew (Unified Stream
      // accumulating messages, Open Positions accumulating reconciled
      // orphans, etc.). That outer scroll dragged the chart container
      // taller — the chart's ResizeObserver then re-sized the chart
      // vertically with each new stream message, which is the bug
      // operator reported. Clamp the root to the viewport (`overflow-
      // hidden` + `h-full` via the existing `top-0…bottom-0` fixed
      // bounds). Inner panels already have their own `overflow-y-auto`
      // so they scroll internally instead of pushing siblings around.
      className="fixed top-0 right-0 bottom-0 left-[52px] z-30 bg-zinc-950 text-zinc-100 flex flex-col overflow-hidden v5-root"
    >
      {/* Safety kill-switch banner — z-60, above everything when tripped */}
      <SafetyBannerV5 safety={safety} />

      {/* v19.30.11 (2026-05-01) — System Banner: catastrophic-subsystem
          alert strip with explicit operator-action copy. Renders giant
          red strip when pusher_rpc has been red ≥30s, mongo is down,
          etc. Polls /api/system/banner every 10s. The action text
          tells the operator EXACTLY what to do (and what NOT to do —
          e.g., "Do NOT restart the Spark backend, it's healthy"). */}
      <SystemBanner />

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
        totalUnrealizedPnl={totalUnrealizedPnl}
        totalRealizedPnl={totalRealizedPnl}
        totalPnlToday={totalPnlToday}
        closedToday={closedToday}
        winsToday={winsToday}
        lossesToday={lossesToday}
        // v19.31.9 — per-stage drill-down rows + meta
        scanRows={counts.drilldown?.scan}
        evalRows={counts.drilldown?.eval}
        orderRows={counts.drilldown?.order}
        managePositions={counts.drilldown?.manage}
        scanMeta={counts.drilldownMeta?.scan}
        evalMeta={counts.drilldownMeta?.eval}
        orderMeta={counts.drilldownMeta?.order}
        manageMeta={counts.drilldownMeta?.manage}
        onJumpToTrade={(row) => {
          // Reuse the existing focus-symbol bus other panels listen to.
          if (row?.symbol) {
            try {
              window.dispatchEvent(new CustomEvent('sentcom:focus-symbol', {
                detail: { symbol: row.symbol, source: 'pipeline-drilldown' },
              }));
            } catch (_) { /* no-op */ }
          }
        }}
        equity={equity}
        buyingPower={buyingPower}
        phase={phase}
        rightExtra={
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="cmdk-hint"
              data-help-id="cmd-k"
              title="Press ⌘K (Mac) or Ctrl+K to open the symbol search palette"
              onClick={() => window.dispatchEvent(new CustomEvent('sentcom:open-command-palette'))}
              className="hidden md:inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-zinc-800 bg-zinc-950 v5-mono text-[11px] text-zinc-500 uppercase tracking-wide select-none hover:border-violet-700 hover:text-violet-300 transition-colors"
            >
              <kbd className="font-bold text-zinc-400">⌘K</kbd>
              <span className="opacity-60">search</span>
            </button>
            <HealthChip onOpenInspector={() => setInspectorOpen(true)} />
            <ConnectivityCheck />
            <PusherHealthChip />
            <DeadLetterBadge />
            <FlattenAllButtonV5 safety={safety} inline />
            <AccountModeBadge />
            <BootReconcilePill />
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
        <PanelErrorBoundary label="shadow-vs-real" compact>
          <ShadowVsRealTile />
        </PanelErrorBoundary>
      </div>

      {/* 2. Main content row (2026-04-30 v19.9):
          • LEFT column (20%) — Scanner spanning the FULL viewport height
            so the operator can scroll through many hits without the
            bottom drawer cutting underneath.
          • RIGHT column (80%) — Chart grid on top + bottom twin-drawer
            beneath, both aligned to the chart's left edge.
          Prior layout had the drawer spanning 100% under a Scanner
          that was only as tall as the grid, wasting vertical space. */}
      <div
        data-testid="sentcom-v5-main-row"
        // v19.34.1 (2026-05-04) — was `flex-shrink-0 min-h-[1120px]`,
        // which set only the LOWER bound and refused to shrink. As
        // inner panels grew with content, this row grew with them and
        // (via the formerly-overflow-y-auto root) dragged the chart
        // taller. Switched to `flex-1 min-h-0` so the row claims all
        // remaining viewport height after the strips above and never
        // exceeds it. Inner panels (Scanner, Stream, Open Positions)
        // each scroll internally via their own `overflow-y-auto`.
        className="flex flex-1 min-h-0 gap-px bg-zinc-900"
      >
        {/* LEFT — Scanner · Live (full height) */}
        <section
          data-testid="sentcom-v5-left"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0 flex-shrink-0"
          style={{ width: '20%' }}
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
            <div className="flex items-center gap-2">
              <div className="v5-panel-title">Scanner · Live</div>
              <LiveDataChip compact />
            </div>
            <div className="flex items-center gap-2">
              <span
                className="text-[10px] v5-mono text-zinc-600 hidden sm:inline"
                title="Keyboard navigation: ↓/↑ move cursor, Enter opens chart"
              >
                ↓↑ ⏎
              </span>
              <div className="text-[11px] v5-mono text-zinc-500" data-testid="v5-scanner-hits-count">
                {(() => {
                  // 2026-04-30 v19.10 — when the scanner has cards,
                  // show "X / N hits" with X = topmost-visible card.
                  // Falls back to set-based count from raw inputs while
                  // ScannerCardsV5's effect is wiring up on first mount.
                  if (scanProgress.total > 0) {
                    const x = Math.min(scanProgress.topIdx + 1, scanProgress.total);
                    return `${x} / ${scanProgress.total} ${scanProgress.total === 1 ? 'hit' : 'hits'}`;
                  }
                  const syms = new Set();
                  (setups || []).forEach(s => s?.symbol && syms.add(String(s.symbol).toUpperCase()));
                  (alerts || []).forEach(a => a?.symbol && syms.add(String(a.symbol).toUpperCase()));
                  (positions || []).forEach(p => p?.symbol && syms.add(String(p.symbol).toUpperCase()));
                  const n = syms.size;
                  return `${n} ${n === 1 ? 'hit' : 'hits'}`;
                })()}
              </div>
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
                hoveredSymbol={hoveredSymbol}
                onHoverSymbol={handleHoverSymbol}
                onScanProgress={setScanProgress}
              />
            </PanelErrorBoundary>
          </div>
        </section>

        {/* RIGHT — everything else stacked. Chart + right sidebar on
            top; SentCom Intelligence + Deep Feed drawer beneath.
            `flex-1 min-w-0` so it consumes the remaining 80%. */}
        <div className="flex-1 min-w-0 flex flex-col gap-px bg-zinc-900">
          {/* Top grid: Chart center + Right sidebar (aligned to the
              chart's left edge). 55fr/25fr = the old 55%/25% split
              repurposed for the right column.
              v19.34.1 (2026-05-04) — was `flex-shrink-0 min-h-[800px]`,
              which set only the LOWER bound. As Unified Stream messages
              accumulated, the inner stream's natural height grew
              unboundedly, dragging the grid (and chart container) taller
              with it. Switched to `flex-1 min-h-0`: the grid claims ALL
              remaining vertical space in the column flex-col, no more,
              no less. Inside each grid cell, the existing `flex: 60/40`
              children + `overflow-hidden` chain on the stream now have
              a deterministic parent height to flex-distribute against,
              so the stream's `flex-1 overflow-y-auto` finally scrolls
              internally instead of pushing the chart taller. */}
          <div
            data-testid="sentcom-v5-grid"
            className="grid gap-px bg-zinc-900 flex-1 min-h-0"
            style={{ gridTemplateColumns: '55fr 25fr' }}
          >

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
              <EodCountdownBannerV5 />
              <DayRollupBannerV5 apiBase={process.env.REACT_APP_BACKEND_URL || ''} />
              <UnifiedStreamV5 messages={messages} loading={streamLoading} onSymbolClick={handleOpenTicker} hoveredSymbol={hoveredSymbol} onHoverSymbol={handleHoverSymbol} />
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

        {/* RIGHT — Briefings strip on top + Open Positions filling rest.
            Briefings collapsed to a compact pulse-button strip
            (2026-04-29 afternoon-10) so positions get the bulk of the
            sidebar height. Click any briefing button → modal with the
            full card. Active-window briefings pulse green. */}
        <aside
          data-testid="sentcom-v5-right"
          className="bg-zinc-950 flex flex-col overflow-hidden min-w-0"
        >
          {/* Briefings strip — collapsed, always visible at the top */}
          <div
            className="border-b border-zinc-800 px-2 py-2 flex-shrink-0"
            data-testid="briefings-strip-container"
          >
            <PanelErrorBoundary label="briefings-strip">
              <BriefingsCompactStrip
                context={context}
                positions={positions}
                totalPnl={totalPnl}
                onSymbolClick={handleOpenTicker}
                onOpenDeepDive={onOpenBriefingDeepDive}
              />
            </PanelErrorBoundary>
          </div>

          {/* 2026-05-01 v19.22 — ML Feature Audit panel.
              Lets the operator click any $TICKER (gap-scanner, briefing
              chip, etc.) and instantly see which label-features fired
              (market_setup + multi_index_regime + sector_regime) — i.e.
              "is the learning loop wired for this trade?". Listens for
              the same `sentcom:focus-symbol` event the chat hook uses,
              so a single click on any chip lights up BOTH this panel
              and the chat. CpuReliefBadge sits next to it as a small
              status chip — manual toggle for the throttle. */}
          <div
            className="border-b border-zinc-800 px-2 py-2 flex-shrink-0 space-y-2"
            data-testid="ml-audit-strip-container"
          >
            <div className="flex items-center justify-end">
              <CpuReliefBadge />
            </div>
            <PanelErrorBoundary label="ml-audit-panel">
              <MLFeatureAuditPanel />
            </PanelErrorBoundary>
          </div>

          {/* Open positions — gets ALL remaining vertical room now */}
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
        {/* End of top grid (chart + right sidebar) */}

        {/* Bottom drawer — TWIN LIVE PANELS (2026-04-29 afternoon-10).
            Replaces the prior trio of reflection panels (Model Health,
            Smart Levels Analytics, AI Decision Audit), all of which were
            static during market hours and have been moved to NIA.
            Now: 60% SentCom Intelligence (live confidence-gate decisions
            + trading mode banner), 40% Unified Stream mirror (deeper
            history view; the chart-side stream stays for action-context
            reading).
            2026-04-30 v19.9: moved INSIDE the right column so its left
            edge aligns with the chart — Scanner (left 20%) now spans
            the full viewport height without the drawer cutting
            underneath. */}
        <div
          className="border-t border-zinc-800 flex-shrink-0 bg-zinc-950"
          style={{ height: '32vh', minHeight: '320px' }}
          data-testid="sentcom-v5-bottom-drawer"
        >
          <div
            ref={drawerContainerRef}
            className="flex h-full bg-zinc-900"
            data-testid="sentcom-v5-drawer-split"
          >
            <div
              className="bg-zinc-950 h-full overflow-hidden"
              style={{ width: `calc(${leftPct}% - 2px)` }}
            >
              <PanelErrorBoundary label="sentcom-intelligence-compact">
                <SentComIntelligencePanel compact />
              </PanelErrorBoundary>
            </div>
            <DrawerSplitHandle
              containerRef={drawerContainerRef}
              onChange={setLeftPct}
              onReset={resetToDefault}
            />
            <div
              className="bg-zinc-950 flex flex-col overflow-hidden h-full"
              style={{ width: `calc(${100 - leftPct}% - 2px)` }}
            >
              <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
                <div className="v5-panel-title">Stream · Deep Feed</div>
                <span className="v5-chip v5-chip-manage">history</span>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                <PanelErrorBoundary label="deep-feed">
                  <DeepFeedV5
                    apiBase={process.env.REACT_APP_BACKEND_URL || ''}
                    onSymbolClick={handleOpenTicker}
                    hoveredSymbol={hoveredSymbol}
                    onHoverSymbol={handleHoverSymbol}
                  />
                </PanelErrorBoundary>
              </div>
            </div>
          </div>
        </div>
        {/* End right column */}
        </div>
      </div>
      {/* End main 2-col row (Scanner | RightColumn) */}

      {/* Corner watermark — lets users opt out to v4 */}
      <div
        data-testid="sentcom-v5-badge"
        className="fixed bottom-1 right-2 text-[11px] v5-mono text-zinc-600 pointer-events-none z-50"
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

  // 2026-05-01 v19.23 — derive trade status + age + change% to mirror
  // the V5 mockup chip strip ("ORDER · 8s · $880.30 · +2.4% · Entry · SL · PT · R:R").
  const status = (position?.status || '').toUpperCase();
  const ageStr = (() => {
    const ts = position?.entry_time;
    if (!ts) return null;
    const t = new Date(ts).getTime();
    if (Number.isNaN(t)) return null;
    const diffSec = Math.floor((Date.now() - t) / 1000);
    if (diffSec < 60) return `${diffSec}s`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`;
    return `${Math.floor(diffSec / 86400)}d`;
  })();

  const currentPx = position?.current_price ?? position?.entry_price;
  const entryPx = position?.entry_price;
  const changePct = (() => {
    if (currentPx == null || entryPx == null || !entryPx) return null;
    const sign = dir === 'short' ? -1 : 1;
    return sign * ((Number(currentPx) - Number(entryPx)) / Number(entryPx)) * 100;
  })();

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
            className="bg-transparent border border-zinc-800 focus:border-cyan-700 focus:outline-none rounded px-2 py-[2px] text-[13px] v5-mono uppercase tracking-wider w-28 placeholder-zinc-600 text-zinc-200"
          />
        )}
        <LiveDataChip />
        <CarouselCountdownChip
          onManualPick={onCarouselPick}
          userHasFocused={userHasFocused}
          currentChartSymbol={symbol}
        />
        {focusedSymbolIsPosition && (
          <span
            className={`v5-chip ${dir === 'short' ? 'v5-chip-veto' : 'v5-chip-manage'}`}
            data-testid="chart-header-status-chip"
          >
            {status || (dir === 'short' ? 'SHORT' : 'LONG')}{ageStr ? ` · ${ageStr}` : ''}
          </span>
        )}
        {focusedSymbolIsPosition && currentPx != null && (
          <div className="flex items-baseline gap-1.5 v5-mono text-[12px]">
            <span className="font-bold text-zinc-100">${Number(currentPx).toFixed(2)}</span>
            {changePct != null && (
              <span
                className={changePct >= 0 ? 'v5-up font-semibold' : 'v5-down font-semibold'}
                data-testid="chart-header-change-pct"
              >
                {changePct >= 0 ? '+' : ''}{changePct.toFixed(1)}%
              </span>
            )}
          </div>
        )}
        {position && (
          <div className="flex items-center gap-2 pl-3 border-l border-zinc-800 text-[12px] v5-mono">
            {position.entry_price != null && (<><span className="v5-dim">Entry</span><span className="v5-warn font-bold">{Number(position.entry_price).toFixed(2)}</span></>)}
            {position.stop_price != null && (<><span className="v5-dim ml-1">SL</span><span className="v5-down font-bold">{Number(position.stop_price).toFixed(2)}</span></>)}
            {(() => {
              const pt = position.target_price ?? (Array.isArray(position.target_prices) ? position.target_prices[0] : null);
              return pt != null ? (<><span className="v5-dim ml-1">PT</span><span className="v5-up font-bold">{Number(pt).toFixed(2)}</span></>) : null;
            })()}
            {(() => {
              const rr = position.risk_reward_ratio ?? position.risk_reward;
              return rr != null && Number(rr) > 0 ? (
                <><span className="v5-dim ml-1">R:R</span><span className="font-bold text-zinc-200">{Number(rr).toFixed(1)}</span></>
              ) : null;
            })()}
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
