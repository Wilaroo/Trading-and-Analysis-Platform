/**
 * TopStrip — V6 shell composite (§4: SENTCOM | pipeline pills | PAPER | state-pill | AI).
 *
 * The real, pure, prop-driven version of the V6NextMockup top strip. Composes
 * the extracted Phase A pieces — the ORDER pill reuses `utils/orderPipelineSplit`
 * so the `5q + 3@ib` split is NEVER reimplemented (invariant #1). The state pill
 * is driven by `appState` ('cyan' | 'amber' | 'rose' — §3 compute_app_state);
 * the Phase-B `useAppState()` hook (backed by /api/safety/system-state) will
 * feed it live. Props in, JSX out — zero coupling to V5.
 */
import React from 'react';
import { Bot } from 'lucide-react';
import { orderPipelineSplit } from '../../../utils/orderPipelineSplit';

const PILL = {
  zinc:    'bg-zinc-800/50 text-zinc-300 border-zinc-700/60',
  cyan:    'bg-cyan-900/40 text-cyan-300 border-cyan-700/60',
  emerald: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/60',
  amber:   'bg-amber-900/40 text-amber-300 border-amber-700/60',
  rose:    'bg-rose-900/40 text-rose-300 border-rose-700/60',
};

const Pill = ({ color = 'zinc', className = '', children, testId }) => (
  <span
    data-testid={testId}
    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[11px] ${PILL[color]} ${className}`.trim()}
  >
    {children}
  </span>
);

const Arrow = () => <span className="text-zinc-700 mx-0.5">→</span>;

const STATE_META = {
  cyan:  { color: 'cyan',  icon: '✓', label: 'ALL SYSTEMS',  detail: '0 drift · 0 thr · 0 orph' },
  amber: { color: 'amber', icon: '⚠', label: 'ELEVATED',     detail: 'warnings active' },
  rose:  { color: 'rose',  icon: '✕', label: 'CRITICAL',     detail: 'action required' },
};

export const TopStrip = ({
  pipeline = {},
  appState = 'cyan',
  stateMeta,
  account = 'PAPER',
  onToggleChat,
  chatOpen = false,
}) => {
  const { scan = 0, eval: evalCount = 0, manage = 0, manageAccent, close = 0, orderPipeline = {} } = pipeline;
  const order = orderPipelineSplit(orderPipeline);
  const hasSplit = order.split && (order.split.ibPending ?? 0) > 0;
  const s = (stateMeta && stateMeta[appState]) || STATE_META[appState] || STATE_META.cyan;

  return (
    <div
      data-testid="v6-topstrip"
      className="bg-zinc-950 border-b border-zinc-800 px-3 py-1.5 flex items-center gap-2 flex-shrink-0 text-[12px]"
    >
      <span className="text-cyan-400 font-bold tracking-wider">SENTCOM</span>

      {/* Pipeline pills — ORDER reuses orderPipelineSplit */}
      <div className="flex items-center gap-0.5 ml-2" data-testid="v6-topstrip-pipeline">
        <Pill color="zinc"><span className="text-zinc-500">SCAN</span> <span className="font-mono font-bold text-zinc-100">{scan}</span></Pill>
        <Arrow />
        <Pill color="cyan"><span className="text-zinc-500">EVAL</span> <span className="font-mono font-bold">{evalCount}</span></Pill>
        <Arrow />
        <Pill color={hasSplit ? 'amber' : 'zinc'} testId="v6-topstrip-order">
          <span className="text-zinc-500">ORDER</span>{' '}
          {hasSplit ? (
            <span className="font-mono font-bold text-zinc-100" data-testid="v6-topstrip-order-split">
              {order.split.queued}<span className="text-zinc-500 font-normal">q</span>
              <span className="text-zinc-600">+</span>
              <span className="text-amber-300">{order.split.ibPending}</span><span className="text-zinc-500 font-normal">@ib</span>
            </span>
          ) : (
            <span className="font-mono font-bold text-zinc-100">{order.total}</span>
          )}
        </Pill>
        <Arrow />
        <Pill color="emerald">
          <span className="text-zinc-500">MANAGE</span> <span className="font-mono font-bold">{manage}</span>
          {manageAccent && <span className="text-emerald-400 font-mono">{manageAccent}</span>}
        </Pill>
        <Arrow />
        <Pill color="emerald"><span className="text-zinc-500">CLOSE</span> <span className="font-mono font-bold">{close}</span></Pill>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <Pill color="amber" testId="v6-topstrip-account">{account}</Pill>
        <Pill color={s.color} testId="v6-topstrip-state">
          <span className="font-bold" data-state={appState}>{s.icon}</span> {s.label}
          <span className="text-zinc-500 font-mono ml-1 text-[10px]">{s.detail}</span>
        </Pill>
        <button
          data-testid="v6-topstrip-ai-btn"
          onClick={onToggleChat}
          className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors ${chatOpen ? 'bg-cyan-700/60 border-cyan-400 text-cyan-50' : 'bg-cyan-900/30 border-cyan-700/60 text-cyan-300 hover:bg-cyan-900/60'}`}
        >
          <Bot className="w-3.5 h-3.5" />
          <span className="text-[12px] font-medium">AI</span>
          <span className="text-zinc-500 font-mono text-[10px]">⌘K</span>
        </button>
      </div>
    </div>
  );
};

export default TopStrip;
