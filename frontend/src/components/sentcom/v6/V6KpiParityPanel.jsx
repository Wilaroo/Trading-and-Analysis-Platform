/**
 * V6KpiParityPanel — Phase C1 field-drift audit overlay (dev/operator tool).
 *
 * The V6 KPI ribbon + pipeline pills read the SAME `/api/sentcom/status`,
 * `/api/sentcom/positions` and `/api/ib/pusher-health` fields the V5 HUD uses.
 * In the sandbox those fields are empty, so drift can only surface against the
 * LIVE IB feed on the DGX. This panel makes that verifiable at a glance: for
 * every ribbon value it shows the resolved source field, the raw value the live
 * feed returned, and the formatted display — flagging any expected field that
 * came back missing/null (the field-name-drift signal).
 *
 * Pure presentational — every value is passed in. Toggled from the V6 shell's
 * preview toolbar; never rendered in the default V5 cockpit.
 */
import React from 'react';
import { CheckCircle2, AlertTriangle, X } from 'lucide-react';
import { formatMoney, formatEquity } from './KpiMetric';

const StatusIcon = ({ ok }) =>
  ok ? (
    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
  ) : (
    <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
  );

const Row = ({ label, source, raw, display, ok, testId }) => (
  <tr className="border-b border-white/5" data-testid={testId} data-ok={ok}>
    <td className="py-1.5 pr-3 align-top"><StatusIcon ok={ok} /></td>
    <td className="py-1.5 pr-3 text-zinc-200 font-medium whitespace-nowrap">{label}</td>
    <td className="py-1.5 pr-3 font-mono text-[10px] text-cyan-300/80 whitespace-nowrap">{source}</td>
    <td className="py-1.5 pr-3 font-mono text-[11px] text-zinc-400 max-w-[260px] break-all">{raw}</td>
    <td className="py-1.5 font-mono text-[11px] text-zinc-100 text-right whitespace-nowrap">{display}</td>
  </tr>
);

export const V6KpiParityPanel = ({
  status,
  context,
  openPositions = [],
  pusher,
  equity,
  buyingPower,
  openRisk,
  dayPnl,
  pipeline = {},
  onClose,
}) => {
  // ── equity / buying-power source resolution (mirror V5 fallback chain) ──
  const equitySrc =
    status?.account_equity != null ? ['status.account_equity', status.account_equity]
      : status?.equity != null ? ['status.equity', status.equity]
        : context?.account_equity != null ? ['context.account_equity', context.account_equity]
          : ['(none resolved)', null];
  const bpSrc =
    status?.account_buying_power != null ? ['status.account_buying_power', status.account_buying_power]
      : status?.buying_power != null ? ['status.buying_power', status.buying_power]
        : context?.account_buying_power != null ? ['context.account_buying_power', context.account_buying_power]
          : ['(none resolved)', null];

  const op = openPositions || [];
  const withRisk = op.filter((p) => p?.risk_amount != null).length;
  const openRiskSource =
    op.length === 0 ? 'Σ risk_amount (0 open)'
      : withRisk === op.length ? `Σ risk_amount (${op.length}/${op.length})`
        : `Σ risk_amount (${withRisk}/${op.length}) + (entry−stop)×sh`;

  const ordPipe = pipeline.orderPipeline || {};
  const ordRaw = Object.keys(ordPipe).length
    ? JSON.stringify(ordPipe)
    : '(empty)';

  const rows = [
    {
      label: 'P&L (day)', source: 'positions.total_pnl_today',
      raw: String(dayPnl ?? 'null'), display: formatMoney(dayPnl), ok: dayPnl != null,
      testId: 'v6-parity-pnl',
    },
    {
      label: 'Equity', source: equitySrc[0],
      raw: String(equitySrc[1] ?? 'null'), display: formatEquity(equity), ok: equitySrc[1] != null,
      testId: 'v6-parity-equity',
    },
    {
      label: 'Buying Power', source: bpSrc[0],
      raw: String(bpSrc[1] ?? 'null'), display: formatEquity(buyingPower), ok: bpSrc[1] != null,
      testId: 'v6-parity-bp',
    },
    {
      label: 'Open Risk', source: openRiskSource,
      raw: `${op.length} open · risk_amount on ${withRisk}`,
      display: formatEquity(openRisk), ok: op.length === 0 || withRisk > 0,
      testId: 'v6-parity-openrisk',
    },
    {
      label: 'Pipeline · ORDER', source: 'status.order_pipeline',
      raw: ordRaw, display: String(pipeline.scan != null ? '' : '') + (Object.keys(ordPipe).length ? 'live' : '—'),
      ok: Object.keys(ordPipe).length > 0, testId: 'v6-parity-order',
    },
    {
      label: 'Pipeline · SCAN', source: (status && (pipeline.scan ?? 0)) ? 'setups.length || alerts.length' : 'setups/alerts (empty)',
      raw: String(pipeline.scan ?? 0), display: String(pipeline.scan ?? 0), ok: true,
      testId: 'v6-parity-scan',
    },
    {
      label: 'Pipeline · EVAL', source: 'alerts.length',
      raw: String(pipeline.eval ?? 0), display: String(pipeline.eval ?? 0), ok: true,
      testId: 'v6-parity-eval',
    },
    {
      label: 'Pipeline · MANAGE', source: 'openPositions.length + Σ unrealized_r',
      raw: `${pipeline.manage ?? 0} pos${pipeline.manageAccent ? ` ·${pipeline.manageAccent}` : ''}`,
      display: String(pipeline.manage ?? 0), ok: true, testId: 'v6-parity-manage',
    },
    {
      label: 'Pipeline · CLOSE', source: 'closedToday.length',
      raw: String(pipeline.close ?? 0), display: String(pipeline.close ?? 0), ok: true,
      testId: 'v6-parity-close',
    },
    {
      label: 'RPC (pusher)', source: 'pusher.age_seconds / .health',
      raw: pusher
        ? `age=${pusher.age_seconds ?? 'null'} · health=${pusher.health ?? 'null'} · dead=${!!pusher.pusher_dead}`
        : '(no pusher-health response)',
      display: '—', ok: !!pusher && pusher.health != null,
      testId: 'v6-parity-rpc',
    },
  ];

  const missing = rows.filter((r) => !r.ok).length;

  return (
    <div
      data-testid="v6-kpi-parity-panel"
      className="absolute right-3 top-24 z-50 w-[640px] max-w-[92vw] rounded-lg border border-cyan-500/30 bg-[#07090E]/95 backdrop-blur-xl shadow-2xl"
      style={{ boxShadow: '0 0 40px -12px rgba(34,211,238,0.4)' }}
    >
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/10">
        <div className="flex items-center gap-2">
          <span className="text-cyan-300 font-bold text-[13px] tracking-wide">KPI FIELD AUDIT</span>
          <span className="text-[11px] text-zinc-500">live `/api/sentcom/status` provenance</span>
        </div>
        <div className="flex items-center gap-3">
          <span
            data-testid="v6-parity-summary"
            className={`text-[11px] font-mono px-2 py-0.5 rounded border ${
              missing === 0
                ? 'text-emerald-300 border-emerald-700/50 bg-emerald-900/30'
                : 'text-amber-300 border-amber-700/50 bg-amber-900/30'
            }`}
          >
            {missing === 0 ? 'all fields resolved' : `${missing} field(s) missing/null`}
          </span>
          <button
            data-testid="v6-parity-close"
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-200 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
      <div className="px-4 py-2 max-h-[60vh] overflow-y-auto">
        <table className="w-full text-[12px] border-collapse">
          <thead>
            <tr className="text-[10px] uppercase tracking-widest text-zinc-600 border-b border-white/10">
              <th className="py-1.5 pr-3 text-left w-6"> </th>
              <th className="py-1.5 pr-3 text-left">KPI</th>
              <th className="py-1.5 pr-3 text-left">Source field</th>
              <th className="py-1.5 pr-3 text-left">Raw (live feed)</th>
              <th className="py-1.5 text-right">Display</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => <Row key={r.testId} {...r} />)}
          </tbody>
        </table>
        <p className="text-[10px] text-zinc-600 mt-2 leading-relaxed">
          Open on the DGX during RTH. ✓ = field resolved from the live feed. ⚠ = expected field
          came back missing/null → likely field-name drift between the IB payload and the hooks.
          Compare these against the V5 HUD (route <span className="font-mono text-zinc-400">/</span>) — values must match.
        </p>
      </div>
    </div>
  );
};

export default V6KpiParityPanel;
