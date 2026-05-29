/**
 * laneClassify — v19.34.184 (Mission Control)
 *
 * Client-side MIRROR of backend `services/stream_bus.classify_lane` /
 * `severity_of`. Live WS events already arrive pre-classified (with `lane`
 * and `severity`); this mirror is used ONLY to classify the REST backfill
 * (`/api/sentcom/stream/history`) which returns raw thoughts.
 *
 * Keep in sync with services/stream_bus.py.
 */
export const LANES = ['scanner', 'gates', 'execution', 'position', 'reconciler', 'system'];
export const SEVERITIES = ['info', 'success', 'warn', 'alarm'];

export function classifyLane(actionType, kind, source) {
  const a = String(actionType || '').toLowerCase();
  const k = String(kind || '').toLowerCase();
  const s = String(source || '').toLowerCase();

  if (a.startsWith('scanner_') || s === 'enhanced_scanner') return 'scanner';
  if (['reconcile', 'drift', 'zombie', 'orphan'].some((t) => a.includes(t))
      || a.includes('phantom_v19_31_oca')
      || ['position_reconciler', 'state_integrity_service'].includes(s)) return 'reconciler';
  if (a.startsWith('rejection_') || a.startsWith('eod_no_new_entries')
      || ['evaluating_setup', 'trade_decision', 'wrong_side_stop_recomputed', 'position_stop_capped'].includes(a)
      || s === 'opportunity_evaluator'
      || ['evaluation', 'filter', 'rejection', 'skip'].includes(k)) return 'gates';
  if (['trade_filled', 'trade_executed', 'bracket_attach_blocked', 'order_submitted',
       'partial_fill', 'bracket_attached'].includes(a) || k === 'fill') return 'execution';
  if (['eod_flatten_failed', 'position_memory_disagreement', 'wrong_direction_phantom_swept',
       'stop_proximity', 'stop_to_breakeven', 'trailing_stop_moved', 'target_hit', 'scale_out',
       'time_stop_approaching', 'eod_flatten_initiated'].includes(a)
      || a.includes('swept')
      || ['position_manager', 'position_consolidator', 'bracket_reissue_service'].includes(s)) return 'position';
  if (['safety_block', 'risk_update', 'regime_update', 'market_status', 'breadth_update',
       'heartbeat', 'account_guard', 'pusher_freshness'].includes(a) || k === 'system') return 'system';
  return 'system';
}

export function severityOf(kind, actionType) {
  const k = String(kind || '').toLowerCase();
  const a = String(actionType || '').toLowerCase();
  if (k === 'alarm' || a.includes('failed') || a === 'safety_block' || a.includes('drift')) return 'alarm';
  if (['warning', 'rejection', 'skip', 'filter', 'alert'].includes(k)) return 'warn';
  if (k === 'fill' || a.includes('trigger') || a.includes('reconciled')
      || ['trade_filled', 'trade_executed', 'target_hit', 'stop_to_breakeven'].includes(a)) return 'success';
  return 'info';
}

export const LANE_META = {
  scanner:    { label: 'Scanner',     hint: 'alerts firing / filtered' },
  gates:      { label: 'Gates',       hint: 'evaluation · rejections · sizing' },
  execution:  { label: 'Execution',   hint: 'orders · fills · brackets' },
  position:   { label: 'Position',    hint: 'stops · targets · management' },
  reconciler: { label: 'Reconciler',  hint: 'phantom / drift / sweeps' },
};
