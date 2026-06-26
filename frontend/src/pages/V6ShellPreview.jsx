/**
 * V6ShellPreview — the V6 cockpit SHELL, now reachable at the real `/v6` route
 * (Phase C) AND the legacy `?preview=v6shell` query (kept for back-compat). Zero
 * impact on the live V5 cockpit, which remains the default at `/`. Composes the real
 * extracted/built primitives into the §4 layout skeleton:
 *
 *   Heartbeat (5px) → TopStrip → KpiRibbon → [Rail | Scanner | Chart+Verdict
 *   | Thinking | Open Positions] grid.
 *
 * Phase B (slice a, 2026-06-26): the Scanner + Open Positions slots are now
 * fed by the REAL extracted V5 panels (`ScannerCardsV5`, `OpenPositionsV5`)
 * against the SAME live data hooks the V5 cockpit uses (`useSentCom*`) — so
 * the structural V5→V6 transition is real, not mocked. Chart/Verdict/Thinking
 * remain placeholders for the next increment. The state toggle demos the
 * cyan/amber/rose heartbeat + state pill; `useAppState()` drives them live.
 *
 * Sandbox has no IB/scanner/position data, so panels render their empty states
 * here — the real visual pass is `yarn build` on the DGX.
 */
import React, { useState } from 'react';
import { Heartbeat } from '../components/sentcom/v6/Heartbeat';
import { TopStrip } from '../components/sentcom/v6/TopStrip';
import { KpiRibbon } from '../components/sentcom/v6/KpiRibbon';
import { useAppState } from '../hooks/useAppState';
import { ScannerCardsV5 } from '../components/sentcom/v5/ScannerCardsV5';
import { OpenPositionsV5 } from '../components/sentcom/v5/OpenPositionsV5';
import { useSentComPositions } from '../components/sentcom/hooks/useSentComPositions';
import { useSentComSetups } from '../components/sentcom/hooks/useSentComSetups';
import { useSentComAlerts } from '../components/sentcom/hooks/useSentComAlerts';
import { useSentComStream } from '../components/sentcom/hooks/useSentComStream';
import { V6ActionBar } from '../components/sentcom/v6/V6ActionBar';
import { ThinkingPane } from '../components/sentcom/v6/ThinkingPane';
import { RiskRail } from '../components/sentcom/v6/RiskRail';
import { ChartVerdictPanel } from '../components/sentcom/v6/ChartVerdictPanel';

const PIPELINE = {
  scan: 47,
  eval: 20,
  manage: 9,
  manageAccent: '+3.1R',
  close: 3,
  orderPipeline: { pending: 5, ib_pending: 3, executing: 1, filled: 4, last_ack_s: 1 },
};

const PanelSlot = ({ title, width, fill, children }) => (
  <div
    className="rounded-md border border-white/10 bg-white/[0.02] flex flex-col h-full min-h-0"
    style={width ? { width, flexShrink: 0 } : { flex: 1 }}
    data-testid={`v6-shell-slot-${title.toLowerCase().replace(/[^a-z]+/g, '-')}`}
  >
    <div className="px-3 py-2 border-b border-white/5 text-[11px] uppercase tracking-widest text-zinc-500">{title}</div>
    {fill ? (
      <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
    ) : (
      <div className="flex-1 flex items-center justify-center text-zinc-700 text-xs">{children || 'Phase B'}</div>
    )}
  </div>
);

export const V6ShellPreview = () => {
  // Live app-state from /api/safety/system-state; `override` lets us demo any halo.
  const { state: liveState, stateMeta, signals } = useAppState();
  const [override, setOverride] = useState(null);
  const [forceBar, setForceBar] = useState(false);
  const state = override || liveState;

  // Live SentCom data — same hooks the V5 cockpit uses (DRY; no new fetch path).
  const { positions, totalPnlToday, loading: positionsLoading } = useSentComPositions();
  const { setups } = useSentComSetups();
  const { alerts } = useSentComAlerts();
  const { messages, loading: streamLoading } = useSentComStream();

  const [selectedSymbol, setSelectedSymbol] = useState(null);
  const [hoveredSymbol, setHoveredSymbol] = useState(null);

  return (
    <div className="h-screen overflow-hidden bg-[#09090b] text-zinc-100 flex flex-col font-sans" data-testid="v6-shell-preview">
      <Heartbeat state={state} />
      <TopStrip pipeline={PIPELINE} appState={state} stateMeta={stateMeta} account="PAPER · DUN615665" />
      <KpiRibbon
        dayPnl={totalPnlToday ?? 0}
        equity={104230}
        openRisk={1840}
        orderPipeline={PIPELINE.orderPipeline}
        throttle="1.0×"
        throttleColor="text-emerald-400"
        rpc="2.1s"
        rpcColor="text-emerald-400"
        className="border-b border-white/5"
      />

      {/* halo / state demo toggle (preview-only). LIVE = from /api/system/health */}
      <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-zinc-600">
        <span className="uppercase tracking-widest">state:</span>
        <button
          data-testid="v6-shell-state-live"
          onClick={() => setOverride(null)}
          className={`uppercase font-bold px-2 py-0.5 rounded transition-colors ${!override ? 'bg-zinc-700/60 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300'}`}
        >
          live
        </button>
        {['cyan', 'amber', 'rose'].map((opt) => (
          <button
            key={opt}
            data-testid={`v6-shell-state-${opt}`}
            onClick={() => setOverride(opt)}
            className={`uppercase font-bold px-2 py-0.5 rounded transition-colors ${
              override === opt
                ? opt === 'cyan' ? 'bg-cyan-700/60 text-cyan-100'
                  : opt === 'amber' ? 'bg-amber-700/60 text-amber-100'
                    : 'bg-rose-700/60 text-rose-100'
                : 'text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {opt}
          </button>
        ))}
        <span className="ml-3 text-zinc-700">Additive preview only — live V5 cockpit untouched.</span>
        <button
          data-testid="v6-shell-force-actionbar"
          onClick={() => setForceBar((v) => !v)}
          className={`ml-auto uppercase font-bold px-2 py-0.5 rounded transition-colors ${forceBar ? 'bg-rose-700/60 text-rose-100' : 'text-zinc-500 hover:text-zinc-300'}`}
        >
          {forceBar ? 'hide action bar' : 'preview action bar'}
        </button>
      </div>

      {/* §4 5-col body grid */}
      <div className="flex-1 min-h-0 flex gap-2 p-2 pb-1">
        <RiskRail />
        <PanelSlot title="Scanner" width="230px" fill>
          <ScannerCardsV5
            setups={setups}
            alerts={alerts}
            positions={positions}
            messages={messages}
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            hoveredSymbol={hoveredSymbol}
            onHoverSymbol={setHoveredSymbol}
          />
        </PanelSlot>
        <div className="flex-1 min-w-0 min-h-0">
          <ChartVerdictPanel
            symbol={selectedSymbol}
            position={(positions || []).find((p) => p.symbol === selectedSymbol) || null}
            onSymbolChange={setSelectedSymbol}
            className="h-full"
          />
        </div>
        <div style={{ width: '340px', flexShrink: 0 }} className="min-h-0">
          <ThinkingPane
            state={state}
            symbol={selectedSymbol}
            messages={messages}
            loading={streamLoading}
            onSymbolClick={setSelectedSymbol}
            hoveredSymbol={hoveredSymbol}
            onHoverSymbol={setHoveredSymbol}
            className="h-full"
          />
        </div>
        <PanelSlot title="Open Positions" width="280px" fill>
          <OpenPositionsV5
            positions={positions}
            totalPnl={totalPnlToday ?? 0}
            loading={positionsLoading}
            onSelectPosition={(p) => setSelectedSymbol(p?.symbol || null)}
          />
        </PanelSlot>
      </div>

      <V6ActionBar state={state} signals={signals} forceShow={forceBar} />
    </div>
  );
};

export default V6ShellPreview;
