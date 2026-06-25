/**
 * OrderPipelineMicroBar — V6 Plan A primitive (§v110, V6_INTEGRATION_v110_v114).
 *
 * Thin stacked micro-bar that visualizes the in-flight order pipeline as
 * `pending / ib_pending / executing` segments. Sits underneath the KPI
 * ribbon's "Open Risk" column so the operator reads order-pipeline health at
 * a glance WITHOUT clicking into the ORDER tile.
 *
 *   queued (pending)   → amber   (locally queued work)
 *   ib_pending         → blue    (sitting at IB in PendingSubmit — v109)
 *   executing          → emerald (actively filling)
 *
 * Pure presentational — props in, JSX out. Renders a faint empty track when
 * nothing is in flight (keeps the ribbon row height stable).
 */
import React from 'react';

const SEG = [
  { key: 'pending',    label: 'queued',    cls: 'bg-amber-400' },
  { key: 'ib_pending', label: '@ib',       cls: 'bg-blue-400' },
  { key: 'executing',  label: 'executing', cls: 'bg-emerald-400' },
];

export const OrderPipelineMicroBar = ({ orderPipeline, className = '', testId = 'order-pipeline-microbar' }) => {
  const p = orderPipeline || {};
  const counts = SEG.map((s) => ({ ...s, n: Math.max(0, Number(p[s.key] ?? 0)) }));
  const total = counts.reduce((a, c) => a + c.n, 0);
  const title = total > 0
    ? counts.filter((c) => c.n > 0).map((c) => `${c.n} ${c.label}`).join(' · ')
    : 'no orders in flight';

  return (
    <div
      data-testid={testId}
      title={title}
      className={`mt-1 h-1 w-full rounded-full overflow-hidden flex bg-white/5 ${className}`.trim()}
    >
      {total === 0 ? (
        <div className="w-full bg-white/5" data-testid={`${testId}-empty`} />
      ) : (
        counts.map((c) => (
          c.n > 0 ? (
            <div
              key={c.key}
              data-testid={`${testId}-${c.key}`}
              className={`${c.cls} h-full`}
              style={{ width: `${(c.n / total) * 100}%` }}
            />
          ) : null
        ))
      )}
    </div>
  );
};

export default OrderPipelineMicroBar;
