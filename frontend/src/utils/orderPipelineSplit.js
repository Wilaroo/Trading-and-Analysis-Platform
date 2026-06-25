/**
 * orderPipelineSplit — V6 Plan A Phase A shared primitive (§10, V6_INTEGRATION_v110_v114).
 *
 * Single source of truth for the v19.34.110 ORDER-tile split. Lifted out of
 * `SentComV5View.jsx :: derivePipelineCounts` so the V5 HUD and the V6 TopStrip
 * pipeline pill / KPI ribbon consume ONE implementation (never reimplemented).
 *
 * Input is the `status.order_pipeline` payload from /api/sentcom/status:
 *   { pending, ib_pending, executing, filled | filled_today, last_ack_s }
 *
 * Returns the byte-identical shape `derivePipelineCounts` produced for the
 * order fields:
 *   {
 *     total: number,                                   // ORDER tile count
 *     split: { queued, ibPending } | null,             // null → render flat count
 *     sub:   string,                                   // ORDER tile sub-label
 *   }
 *
 * Rendering contract (invariant #1): when `split.ibPending > 0`, the ORDER
 * pill renders `5q + 3@ib` (see PipelineHUDV5 `Stage` splitCount branch) —
 * never a flat count. V6 must mirror that exact branch.
 */
export function orderPipelineSplit(pipeline) {
  const p = pipeline || {};
  const filled = p.filled ?? p.filled_today ?? 0;

  const total =
    (p.pending ?? 0) + (p.ib_pending ?? 0) + (p.executing ?? 0) + filled;

  const hasSplit =
    p.pending != null || p.ib_pending != null || p.executing != null;
  const split = hasSplit
    ? {
        queued: (p.pending ?? 0) + (p.executing ?? 0),
        ibPending: p.ib_pending ?? 0,
      }
    : null;

  const hasSub =
    p.pending != null || p.filled != null || p.filled_today != null;
  const sub = hasSub
    ? `${filled} filled · ${p.pending ?? 0} pending${
        p.ib_pending ? ` · ${p.ib_pending}@ib` : ''
      }${p.last_ack_s != null ? ` · ${p.last_ack_s}s ack` : ''}`
    : '—';

  return { total, split, sub };
}

export default orderPipelineSplit;
