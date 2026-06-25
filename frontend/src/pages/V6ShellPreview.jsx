/**
 * V6ShellPreview — isolated, additive proof of the V6 cockpit SHELL
 * (?preview=v6shell). Zero impact on the live V5 cockpit. Composes the real
 * extracted/built primitives into the §4 layout skeleton so we can see the
 * V6 frame coming together:
 *
 *   Heartbeat (5px) → TopStrip → KpiRibbon → [Rail | Scanner | Chart+Verdict
 *   | Thinking | Open Positions] placeholder grid.
 *
 * Panel bodies are labelled placeholders for now — Phase B fills them with the
 * extracted V5 panels. The state toggle demos the cyan/amber/rose heartbeat +
 * state pill (the Phase-B `useAppState()` hook will drive these live).
 */
import React, { useState } from 'react';
import { Heartbeat } from '../components/sentcom/v6/Heartbeat';
import { TopStrip } from '../components/sentcom/v6/TopStrip';
import { KpiRibbon } from '../components/sentcom/v6/KpiRibbon';
import { useAppState } from '../hooks/useAppState';

const PIPELINE = {
  scan: 47,
  eval: 20,
  manage: 9,
  manageAccent: '+3.1R',
  close: 3,
  orderPipeline: { pending: 5, ib_pending: 3, executing: 1, filled: 4, last_ack_s: 1 },
};

const PanelSlot = ({ title, width, children }) => (
  <div
    className="rounded-md border border-white/10 bg-white/[0.02] flex flex-col min-h-[420px]"
    style={width ? { width, flexShrink: 0 } : { flex: 1 }}
    data-testid={`v6-shell-slot-${title.toLowerCase().replace(/[^a-z]+/g, '-')}`}
  >
    <div className="px-3 py-2 border-b border-white/5 text-[11px] uppercase tracking-widest text-zinc-500">{title}</div>
    <div className="flex-1 flex items-center justify-center text-zinc-700 text-xs">{children || 'Phase B'}</div>
  </div>
);

export const V6ShellPreview = () => {
  // Live app-state from /api/system/health; `override` lets us demo any halo.
  const { state: liveState, stateMeta } = useAppState();
  const [override, setOverride] = useState(null);
  const state = override || liveState;
  return (
    <div className="min-h-screen bg-[#09090b] text-zinc-100 flex flex-col font-sans" data-testid="v6-shell-preview">
      <Heartbeat state={state} />
      <TopStrip pipeline={PIPELINE} appState={state} stateMeta={stateMeta} account="PAPER · DUN615665" />
      <KpiRibbon
        dayPnl={382.21}
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
      </div>

      {/* §4 5-col body grid */}
      <div className="flex-1 flex gap-2 p-2">
        <PanelSlot title="Rail" width="22px"><span className="rotate-180" style={{ writingMode: 'vertical-rl' }}>DLP</span></PanelSlot>
        <PanelSlot title="Scanner" width="230px" />
        <PanelSlot title="Chart + Verdict" />
        <PanelSlot title="Thinking" width="340px" />
        <PanelSlot title="Open Positions" width="280px" />
      </div>
    </div>
  );
};

export default V6ShellPreview;
