/**
 * EdgePerformanceCluster — unifies the three bot-performance tiles into
 * ONE chip + popover, freeing the status strip for the Regime Strip.
 *
 * Collapsed: an "EDGE & PERFORMANCE" chip.
 * Expanded: a popover stacking the existing cards:
 *   • P&L by Style     (today's realized R / win% / $ by trade-style)
 *   • Strategy Mix     (setup-type distribution + per-setup edge)
 *   • Shadow vs Real   (shadow-AI win% vs real bot win%)
 *
 * The detail container is always mounted (display:none when collapsed)
 * so the cards keep their existing polling cadence.
 */
import React, { useState, useRef, useEffect } from 'react';
import { TrendingUp, ChevronDown } from 'lucide-react';

import { PnLByStyleCard } from './PnLByStyleCard';
import { StrategyMixCard } from './StrategyMixCard';
import { ShadowVsRealTile } from './ShadowVsRealTile';

const Group = ({ title, children }) => (
  <div data-testid={`edge-group-${title.toLowerCase().replace(/\s+/g, '-')}`}>
    <div className="text-[11px] font-bold tracking-wider uppercase text-zinc-500 px-1 pb-1">{title}</div>
    <div className="bg-zinc-900/40 rounded border border-zinc-800 overflow-hidden">{children}</div>
  </div>
);

export const EdgePerformanceCluster = () => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  return (
    <div ref={ref} data-testid="edge-performance-cluster" className="relative flex items-center px-2 py-0.5 bg-zinc-950">
      <button
        type="button"
        data-testid="edge-performance-toggle"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 px-1.5 py-0.5 hover:bg-zinc-900 rounded transition-colors"
        title="Bot edge — P&L by style, strategy mix, shadow vs real"
      >
        <TrendingUp className="w-3 h-3 text-zinc-500" />
        <span className="text-[13px] font-bold tracking-wider text-zinc-300 uppercase">Edge &amp; Performance</span>
        <ChevronDown className={`w-3 h-3 text-zinc-600 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      <div
        data-testid="edge-performance-detail"
        className={open
          ? 'absolute z-[70] left-0 top-full mt-1 w-[700px] max-w-[94vw] bg-zinc-950 border border-zinc-700 shadow-2xl p-2 space-y-2'
          : 'hidden'}
      >
        <Group title="P&L by Style"><PnLByStyleCard /></Group>
        <Group title="Strategy Mix"><StrategyMixCard /></Group>
        <Group title="Shadow vs Real"><ShadowVsRealTile /></Group>
      </div>
    </div>
  );
};

export default EdgePerformanceCluster;
