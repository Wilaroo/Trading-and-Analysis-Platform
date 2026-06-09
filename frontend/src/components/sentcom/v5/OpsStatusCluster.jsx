/**
 * OpsStatusCluster — unifies the six operational-health tiles into ONE
 * status chip with a worst-of dot, freeing the status strip for the
 * Regime Strip.
 *
 * Collapsed: a single "OPS STATUS" chip whose dot = worst-of the 6
 *   subsystems. Safety canaries (Position-Truth-Diff drift, Bracket
 *   reverse-at-IB) break out into a LOUD red badge so collapsing never
 *   hides a real-money problem.
 * Expanded: a popover grouping the existing tiles under three headings:
 *   • Data Feed           → Pusher Heartbeat + Portfolio Health
 *   • Execution Integrity  → Position-Truth-Diff + Bracket Reaper + Cost-Basis Sync
 *   • Signal Funnel        → Scanner Quality
 *
 * The detail container is always mounted (display:none when collapsed)
 * so each child keeps polling and reporting its health via `onStatus`.
 */
import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';

import { PusherHeartbeatTile } from './PusherHeartbeatTile';
import { PortfolioHealthPill } from './PortfolioHealthPill';
import { PositionTruthDiffPill } from './PositionTruthDiffPill';
import { BracketReaperPill } from './BracketReaperPill';
import { CostBasisSyncTile } from './CostBasisSyncTile';
import { ScannerQualityPanel } from './ScannerQualityPanel';
// v316h — pipeline diagnostics folded in from the HUD top strip.
import { BracketsPathPill } from './BracketsPathPill';
import { ConnectivityCheck } from './ConnectivityCheck';
import { ScannerCoverageAuditPanel } from './ScannerCoverageAuditPanel';
import BootReconcilePill from './BootReconcilePill';
import DriftGuardPill from './DriftGuardPill';
import CancelQueueSelfHealPill from './CancelQueueSelfHealPill';

const RANK = { red: 3, amber: 2, unknown: 1, green: 0 };
const DOT = { red: 'bg-rose-500', amber: 'bg-amber-400', unknown: 'bg-zinc-500', green: 'bg-emerald-400' };
const TXT = { red: 'text-rose-300', amber: 'text-amber-300', unknown: 'text-zinc-400', green: 'text-emerald-300' };

const Group = ({ title, children }) => (
  <div data-testid={`ops-group-${title.toLowerCase().replace(/\s+/g, '-')}`}>
    <div className="text-[11px] font-bold tracking-wider uppercase text-zinc-500 px-1 pb-1">{title}</div>
    <div className="flex flex-col bg-zinc-900/40 rounded border border-zinc-800 divide-y divide-zinc-800/60 overflow-hidden">
      {children}
    </div>
  </div>
);

export const OpsStatusCluster = () => {
  const [open, setOpen] = useState(false);
  const [statuses, setStatuses] = useState({});
  const ref = useRef(null);

  const report = useCallback((id, s) => {
    setStatuses((prev) => (prev[id] === s ? prev : { ...prev, [id]: s }));
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const worst = useMemo(() => {
    const vals = Object.values(statuses);
    if (!vals.length) return 'unknown';
    return vals.reduce((w, s) => (RANK[s] > RANK[w] ? s : w), 'green');
  }, [statuses]);

  const nonGreen = Object.entries(statuses).filter(([, s]) => s && s !== 'green').length;
  // Safety canaries escalate loudly even when the cluster is collapsed.
  const truthRed = statuses['truth-diff'] === 'red';
  const bracketRed = statuses['bracket'] === 'red';
  const safetyRed = truthRed || bracketRed;

  return (
    <div ref={ref} data-testid="ops-status-cluster" className="relative flex items-center px-2 py-0.5 bg-zinc-950">
      <button
        type="button"
        data-testid="ops-status-toggle"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 px-1.5 py-0.5 hover:bg-zinc-900 rounded transition-colors"
        title="Operational health — data feed, execution integrity, signal funnel"
      >
        <span className="relative flex h-2 w-2">
          {(worst === 'red' || safetyRed) && (
            <span className={`absolute inline-flex h-full w-full rounded-full ${DOT.red} opacity-70 animate-ping`} />
          )}
          <span data-testid="ops-status-dot" className={`relative inline-flex h-2 w-2 rounded-full ${DOT[worst]}`} />
        </span>
        <span className="text-[13px] font-bold tracking-wider text-zinc-300 uppercase">Ops Status</span>
        {safetyRed ? (
          <span
            data-testid="ops-status-escalation"
            className="px-1.5 py-0.5 rounded text-[12px] font-bold tracking-wider bg-rose-500/20 text-rose-300 border border-rose-500/40 animate-pulse"
          >
            ⚠ {truthRed ? 'POSITION DRIFT' : 'REVERSE@IB'}
          </span>
        ) : nonGreen > 0 ? (
          <span data-testid="ops-status-attn" className={`text-[12px] v5-mono ${TXT[worst]}`}>{nonGreen} attn</span>
        ) : (
          <span data-testid="ops-status-ok" className="text-[12px] v5-mono text-emerald-300">OK</span>
        )}
        <ChevronDown className={`w-3 h-3 text-zinc-600 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {/* Always mounted so children keep polling + reporting; hidden when collapsed. */}
      <div
        data-testid="ops-status-detail"
        className={open
          ? 'absolute z-[70] left-0 top-full mt-1 w-[660px] max-w-[92vw] bg-zinc-950 border border-zinc-700 shadow-2xl p-2 space-y-2 v5-mono'
          : 'hidden'}
      >
        <Group title="Data Feed">
          <PusherHeartbeatTile onStatus={(s) => report('pusher', s)} />
          <PortfolioHealthPill onStatus={(s) => report('portfolio', s)} />
        </Group>
        <Group title="Execution Integrity">
          <div className="px-2 py-1"><PositionTruthDiffPill onStatus={(s) => report('truth-diff', s)} /></div>
          <BracketReaperPill onStatus={(s) => report('bracket', s)} />
          <CostBasisSyncTile onStatus={(s) => report('cost-basis', s)} />
        </Group>
        <Group title="Signal Funnel">
          <ScannerQualityPanel onStatus={(s) => report('scanner', s)} />
        </Group>
        <Group title="Pipeline Diagnostics">
          <div className="flex flex-wrap items-center gap-1.5 p-2">
            <BracketsPathPill />
            <ConnectivityCheck />
            <ScannerCoverageAuditPanel />
            <BootReconcilePill />
            <DriftGuardPill />
            <CancelQueueSelfHealPill />
          </div>
        </Group>
      </div>
    </div>
  );
};

export default OpsStatusCluster;
