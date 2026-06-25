/**
 * V6KpiRibbonPreview — isolated, additive proof page for the Phase A
 * primitives (?preview=v6kpis). Zero impact on the live V5 cockpit; it only
 * renders the extracted/composed V6 building blocks against sample tuples so
 * we can eyeball them in the sandbox (which has no live DGX data).
 *
 * Shows:
 *  - PipelineStageTile in flat AND `5q + 3@ib` split modes (orderPipelineSplit)
 *  - KpiRibbon with the §v110 Open-Risk micro-bar across a few pipeline tuples
 */
import React from 'react';
import { PipelineStageTile } from '../components/sentcom/v6/PipelineStageTile';
import { KpiRibbon } from '../components/sentcom/v6/KpiRibbon';
import { orderPipelineSplit } from '../utils/orderPipelineSplit';

const TUPLES = [
  { label: 'idle',                 pipe: {} },
  { label: 'queued only',          pipe: { pending: 5, executing: 1, filled: 2, last_ack_s: 3 } },
  { label: 'queued + @ib',         pipe: { pending: 5, ib_pending: 3, executing: 1, filled: 4, last_ack_s: 1 } },
  { label: 'all at IB',            pipe: { pending: 0, ib_pending: 6, executing: 0, filled: 9 } },
];

export const V6KpiRibbonPreview = () => {
  return (
    <div className="min-h-screen bg-[#0a0b0f] text-zinc-100 p-8 font-sans" data-testid="v6-kpis-preview">
      <h1 className="text-2xl font-bold tracking-tight mb-1">V6 Plan A — extracted primitives</h1>
      <p className="text-sm text-zinc-500 mb-8">
        PipelineStageTile · KpiMetric · OrderPipelineMicroBar · KpiRibbon · orderPipelineSplit.
        Pure components, zero V5 behavior change.
      </p>

      <h2 className="text-base font-semibold text-zinc-300 mb-3">Pipeline tiles (flat vs split)</h2>
      <div className="flex gap-2 mb-10 max-w-3xl">
        <PipelineStageTile stage="scan" label="Scan" count={47} sub="47 scored" />
        <PipelineStageTile stage="eval" label="Eval" count={20} sub="20 evaluating" />
        {/* split mode — orderPipelineSplit drives `5q + 3@ib` + ack pulse */}
        {(() => {
          const { total, split, sub, lastAckS } = orderPipelineSplit({ pending: 5, ib_pending: 3, executing: 1, filled: 4, last_ack_s: 1 });
          return <PipelineStageTile stage="order" label="Order" count={total} sub={sub} splitCount={split} ackLatencyS={lastAckS} />;
        })()}
        <PipelineStageTile stage="manage" label="Manage" count={9} accent={{ text: '+3.1R', color: 'text-emerald-400' }} sub="9 open" />
        <PipelineStageTile stage="close" label="Close Today" count={3} sub="2W · 1L" />
      </div>

      <h2 className="text-base font-semibold text-zinc-300 mb-3">ORDER ack-latency pulse (is IB responding?)</h2>
      <div className="flex gap-2 mb-10 max-w-2xl">
        <PipelineStageTile stage="order" label="Order" count={6} sub="ack 1s" ackLatencyS={1} />
        <PipelineStageTile stage="order" label="Order" count={6} sub="ack 4s" ackLatencyS={4} />
        <PipelineStageTile stage="order" label="Order" count={6} sub="ack 9s" ackLatencyS={9} />
        <PipelineStageTile stage="order" label="Order" count={0} sub="no orders" />
      </div>

      <h2 className="text-base font-semibold text-zinc-300 mb-3">KPI ribbon + §v110 Open-Risk micro-bar</h2>
      <div className="space-y-3 max-w-3xl">
        {TUPLES.map((t) => (
          <div key={t.label} className="rounded-md border border-white/10 bg-white/[0.02]">
            <div className="px-4 pt-2 text-[11px] uppercase tracking-widest text-zinc-600">{t.label}</div>
            <KpiRibbon
              dayPnl={382.21}
              equity={104230}
              openRisk={1840}
              orderPipeline={t.pipe}
              throttle="1.0×"
              throttleColor="text-emerald-400"
              rpc="2.1s"
              rpcColor="text-emerald-400"
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default V6KpiRibbonPreview;
