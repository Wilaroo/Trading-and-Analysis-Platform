/**
 * pipelineStageColumns — v19.31.9 (2026-05-04)
 *
 * Column configs for each Pipeline HUD stage drill-down. Keep formatting
 * + color logic in one place so the generic <PipelineStageDrilldown>
 * shell stays presentation-only.
 *
 * Each export returns { columns, headerExtras, emptyText, footerHint,
 * defaultSortKey } for one stage.
 */
import React from 'react';
import TradeTypeChip from './TradeTypeChip';

export const formatMoney = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`;
};

export const formatR = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}R`;
};

export const formatTime = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  } catch {
    return '—';
  }
};

export const formatPrice = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return n >= 100 ? n.toFixed(2) : n.toFixed(n < 10 ? 3 : 2);
};

export const formatPct = (v, digits = 1) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
};

// ── v19.34.15a (2026-05-06) — directional shares cell.
// Operator request 2026-05-06: "make short shares red and long shares
// green so the table makes the side instantly readable." We don't
// switch to signed integers internally (BotTrade.shares stays
// positive — flipping signs would touch every share-math call site
// and risk regression on a live system) — purely a display layer.
//
// Long  → emerald digits.
// Short → rose digits with a leading '-' to mirror IB's signed
//         convention so operators eyeballing the bot panel + IB
//         account window side-by-side see the same sign convention.
// Unknown → zinc.
export const directionalSharesCell = (v, row) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const dir = String(row?.direction || row?.side || '').toLowerCase();
  const n = Math.round(Math.abs(Number(v)));
  if (dir === 'short') {
    return (
      <span
        className="text-rose-400 font-semibold"
        data-testid="shares-short"
      >
        {`-${n.toLocaleString()}`}
      </span>
    );
  }
  if (dir === 'long') {
    return (
      <span
        className="text-emerald-400 font-semibold"
        data-testid="shares-long"
      >
        {n.toLocaleString()}
      </span>
    );
  }
  return <span className="text-zinc-400">{n.toLocaleString()}</span>;
};

const REASON_HUMAN = {
  target_hit: 'target',
  stop_hit: 'stop',
  trail_stop_hit: 'trail',
  scale_out: 'scale-out',
  manual_close: 'manual',
  eod_close: 'EOD',
  oca_closed_externally_v19_31: 'OCA ext',
  phantom_auto_swept_v19_27: 'phantom',
  daily_loss_limit: 'daily-loss',
  reduce_size: 'reduce',
};

const dirCell = (dir) => {
  const isShort = (dir || '').toLowerCase() === 'short';
  return (
    <span className={isShort ? 'text-rose-400' : 'text-emerald-400'}>
      {isShort ? 'S' : 'L'}
    </span>
  );
};

const moneyCell = (v) => {
  const n = Number(v) || 0;
  return (
    <span className={n >= 0 ? 'text-emerald-400 font-semibold' : 'text-rose-400 font-semibold'}>
      {formatMoney(v)}
    </span>
  );
};

const rCell = (v) => {
  const n = Number(v) || 0;
  if (v == null || Number.isNaN(Number(v))) return <span className="text-zinc-600">—</span>;
  return (
    <span className={n >= 0 ? 'text-emerald-400 font-semibold' : 'text-rose-400 font-semibold'}>
      {formatR(v)}
    </span>
  );
};

// ───── Filter helpers ──────────────────────────────────────────────

const humanizeSetup = (s) => (s ? String(s).replace(/_/g, ' ').slice(0, 20) : '?');
const humanizeDir = (d) => {
  const s = String(d || '').toLowerCase();
  if (s === 'long') return 'long';
  if (s === 'short') return 'short';
  return s || '?';
};

const TIER_ORDER = ['SMB-A', 'SMB-B', 'tier1', 'tier2', 'tier3', 'A', 'B', 'C'];
const sortTier = (values) => {
  const ranked = [];
  const rest = [];
  for (const v of values) {
    if (TIER_ORDER.includes(v)) ranked.push(v);
    else rest.push(v);
  }
  ranked.sort((a, b) => TIER_ORDER.indexOf(a) - TIER_ORDER.indexOf(b));
  return [...ranked, ...rest];
};

const STATUS_ORDER = ['filled', 'partial', 'pending', 'submitted', 'rejected', 'cancelled', 'canceled'];
const sortStatus = (values) =>
  [...values].sort((a, b) => {
    const ai = STATUS_ORDER.indexOf(String(a).toLowerCase());
    const bi = STATUS_ORDER.indexOf(String(b).toLowerCase());
    if (ai === -1 && bi === -1) return String(a).localeCompare(String(b));
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

// ───── CLOSE TODAY ──────────────────────────────────────────────────

export const closeStageConfig = ({ totalRealized, winsToday, lossesToday, sortedRows }) => {
  const winRate = (winsToday + lossesToday) > 0
    ? Math.round((winsToday / (winsToday + lossesToday)) * 100)
    : null;
  const sumR = (sortedRows || []).reduce((s, r) => s + (Number(r.r_multiple) || 0), 0);
  return {
    title: 'Closed Today',
    versionTag: 'v19.31.10',
    defaultSortKey: 'closed_at',
    emptyText: 'No trades closed today yet.',
    filters: [
      { key: 'direction',    label: 'Dir',    values: 'auto', format: humanizeDir },
      { key: 'setup_type',   label: 'Setup',  values: 'auto', format: humanizeSetup, maxValues: 6 },
      { key: 'close_reason', label: 'Reason', values: 'auto',
        format: (v) => REASON_HUMAN[v] || v || '?', maxValues: 6 },
      { key: 'trade_type',   label: 'Mode',   values: 'auto',
        format: (v) => (v || '?').toUpperCase() },
    ],
    headerExtras: (
      <>
        {winRate != null && (
          <span data-testid="drilldown-winrate" className="v5-mono text-[11px] text-zinc-500">
            WR {winRate}% · {winsToday}W / {lossesToday}L
          </span>
        )}
        <span
          data-testid="drilldown-realized"
          className={`v5-mono text-[11px] ${(totalRealized ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
        >
          {formatMoney(totalRealized)}
        </span>
        <span
          data-testid="drilldown-sum-r"
          className={`v5-mono text-[11px] ${sumR >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
        >
          {formatR(sumR)}
        </span>
      </>
    ),
    columns: [
      { key: 'symbol',       label: 'Sym',    align: 'left',  width: 'w-14',
        cellClass: () => 'font-bold text-zinc-100' },
      { key: 'direction',    label: 'Dir',    align: 'left',  width: 'w-10',
        render: dirCell, cellClass: () => '' },
      { key: 'shares',       label: 'Sh',     align: 'right', width: 'w-12' },
      { key: 'entry_price',  label: 'Entry',  align: 'right', width: 'w-16',
        render: formatPrice, cellClass: () => 'text-zinc-400' },
      { key: 'exit_price',   label: 'Exit',   align: 'right', width: 'w-16',
        render: formatPrice, cellClass: () => 'text-zinc-400' },
      { key: 'realized_pnl', label: '$',      align: 'right', width: 'w-20',
        render: moneyCell, cellClass: () => '' },
      { key: 'r_multiple',   label: 'R',      align: 'right', width: 'w-14',
        render: rCell, cellClass: () => '' },
      { key: 'close_reason', label: 'Reason', align: 'left',  width: 'w-20',
        render: (v) => REASON_HUMAN[v] || v || '—',
        cellClass: () => 'text-zinc-500' },
      { key: 'trade_type',   label: 'Mode',   align: 'left',  width: 'w-16',
        render: (v) => <TradeTypeChip type={v} hideUnknown size="xs" />,
        cellClass: () => '' },
      { key: 'closed_at',    label: 'Time',   align: 'right', width: 'w-14',
        render: formatTime, cellClass: () => 'text-zinc-500' },
    ],
  };
};

// ───── MANAGE (currently open) ───────────────────────────────────────

export const manageStageConfig = ({ totalUnrealized, sumR }) => ({
  title: 'Open Positions',
  versionTag: 'v19.31.10',
  defaultSortKey: 'pnl',
  emptyText: 'No open positions.',
  filters: [
    { key: 'direction',  label: 'Dir',    values: 'auto', format: humanizeDir },
    { key: 'setup_type', label: 'Setup',  values: 'auto', format: humanizeSetup, maxValues: 6 },
    { key: 'source',     label: 'Source', values: 'auto', format: (v) => v || '?' },
    { key: 'risk_level', label: 'Risk',   values: 'auto', format: (v) => v || '?' },
    { key: 'trade_type', label: 'Mode',   values: 'auto',
      format: (v) => (v || '?').toUpperCase() },
  ],
  headerExtras: (
    <>
      <span
        className={`v5-mono text-[11px] ${(totalUnrealized ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
      >
        {formatMoney(totalUnrealized)}
      </span>
      <span
        className={`v5-mono text-[11px] ${(sumR ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
      >
        {formatR(sumR)}
      </span>
    </>
  ),
  columns: [
    { key: 'symbol',         label: 'Sym',      align: 'left',  width: 'w-14',
      cellClass: () => 'font-bold text-zinc-100' },
    { key: 'direction',      label: 'Dir',      align: 'left',  width: 'w-10',
      render: dirCell, cellClass: () => '' },
    { key: 'shares',         label: 'Sh',       align: 'right', width: 'w-14',
      render: directionalSharesCell, cellClass: () => 'v5-mono' },
    { key: 'entry_price',    label: 'Entry',    align: 'right', width: 'w-16',
      render: formatPrice, cellClass: () => 'text-zinc-400' },
    { key: 'current_price',  label: 'Last',     align: 'right', width: 'w-16',
      render: formatPrice, cellClass: () => 'text-zinc-400' },
    { key: 'pnl',            label: '$',        align: 'right', width: 'w-20',
      render: moneyCell, cellClass: () => '' },
    { key: 'pnl_r',          label: 'R',        align: 'right', width: 'w-14',
      render: rCell, cellClass: () => '' },
    { key: 'stop_price',     label: 'Stop',     align: 'right', width: 'w-16',
      render: formatPrice, cellClass: () => 'text-zinc-400' },
    { key: 'setup_type',     label: 'Setup',    align: 'left',  width: 'w-20',
      render: (v) => v ? String(v).replace(/_/g, ' ').slice(0, 18) : '—',
      cellClass: () => 'text-zinc-500 truncate' },
    { key: 'source',         label: 'Src',      align: 'left',  width: 'w-12',
      cellClass: () => 'text-zinc-500' },
    { key: 'trade_type',     label: 'Mode',     align: 'left',  width: 'w-16',
      render: (v) => <TradeTypeChip type={v} hideUnknown size="xs" />,
      cellClass: () => '' },
  ],
});

// ───── ORDER (placed today) ──────────────────────────────────────────

const ORDER_STATUS_COLOR = {
  filled:    'text-emerald-400',
  partial:   'text-amber-400',
  pending:   'text-sky-400',
  submitted: 'text-sky-400',
  rejected:  'text-rose-400',
  cancelled: 'text-zinc-500',
  canceled:  'text-zinc-500',
};

export const orderStageConfig = ({ filledCount, pendingCount }) => ({
  title: 'Orders Today',
  versionTag: 'v19.31.10',
  defaultSortKey: 'placed_at',
  emptyText: 'No orders placed today.',
  filters: [
    { key: 'direction',  label: 'Dir',    values: 'auto', format: humanizeDir },
    { key: 'status',     label: 'Status', values: 'auto', sort: sortStatus },
    { key: 'order_type', label: 'Type',   values: 'auto', format: (v) => v || '?' },
  ],
  headerExtras: (
    <>
      <span className="v5-mono text-[11px] text-emerald-400">{filledCount} filled</span>
      <span className="v5-mono text-[11px] text-sky-400">{pendingCount} pending</span>
    </>
  ),
  columns: [
    { key: 'symbol',     label: 'Sym',    align: 'left',  width: 'w-14',
      cellClass: () => 'font-bold text-zinc-100' },
    { key: 'direction',  label: 'Dir',    align: 'left',  width: 'w-10',
      render: dirCell, cellClass: () => '' },
    { key: 'shares',     label: 'Sh',     align: 'right', width: 'w-14',
      render: directionalSharesCell, cellClass: () => 'v5-mono' },
    { key: 'order_type', label: 'Type',   align: 'left',  width: 'w-14',
      cellClass: () => 'text-zinc-500' },
    { key: 'limit_price', label: 'Limit', align: 'right', width: 'w-16',
      render: formatPrice, cellClass: () => 'text-zinc-400' },
    { key: 'fill_price',  label: 'Fill',  align: 'right', width: 'w-16',
      render: formatPrice, cellClass: () => 'text-zinc-400' },
    { key: 'status',     label: 'Status', align: 'left',  width: 'w-16',
      cellClass: (v) => ORDER_STATUS_COLOR[String(v || '').toLowerCase()] || 'text-zinc-400' },
    { key: 'placed_at',  label: 'Time',   align: 'right', width: 'w-14',
      render: formatTime, cellClass: () => 'text-zinc-500' },
  ],
});

// ───── EVAL (alerts that hit AI council) ─────────────────────────────

export const evalStageConfig = ({ avgGate, gatePassPct }) => ({
  title: 'Evaluations Today',
  versionTag: 'v19.31.10',
  defaultSortKey: 'gate_score',
  emptyText: 'No evaluations yet.',
  filters: [
    { key: 'tier',                    label: 'Tier',   values: 'auto', sort: sortTier },
    { key: 'setup_type',              label: 'Setup',  values: 'auto', format: humanizeSetup, maxValues: 6 },
    { key: 'combined_recommendation', label: 'AI',     values: 'auto',
      format: (v) => String(v || '?').toLowerCase() },
  ],
  headerExtras: (
    <>
      {avgGate != null && (
        <span className="v5-mono text-[11px] text-zinc-500">avg {avgGate}</span>
      )}
      {gatePassPct != null && (
        <span className="v5-mono text-[11px] text-emerald-400">{gatePassPct}% pass</span>
      )}
    </>
  ),
  columns: [
    { key: 'symbol',           label: 'Sym',    align: 'left',  width: 'w-14',
      cellClass: () => 'font-bold text-zinc-100' },
    { key: 'gate_score',       label: 'Gate',   align: 'right', width: 'w-12',
      render: (v) => v != null ? Number(v).toFixed(0) : '—',
      cellClass: (v) => (Number(v) >= 60 ? 'text-emerald-400 font-semibold' : 'text-rose-400 font-semibold') },
    { key: 'tier',             label: 'Tier',   align: 'left',  width: 'w-12',
      cellClass: () => 'text-zinc-500' },
    { key: 'setup_type',       label: 'Setup',  align: 'left',  width: 'w-20',
      render: (v) => v ? String(v).replace(/_/g, ' ').slice(0, 18) : '—',
      cellClass: () => 'text-zinc-500 truncate' },
    { key: 'combined_recommendation', label: 'AI',  align: 'left',  width: 'w-14',
      render: (v) => v ? String(v).slice(0, 8) : '—',
      cellClass: (v) => (String(v).toLowerCase() === 'proceed' ? 'text-emerald-400' : 'text-zinc-500') },
    { key: 'reasoning',        label: 'Reason', align: 'left',  width: 'flex-1',
      render: (v) => Array.isArray(v) ? v.slice(0, 1).join(' ').slice(0, 50) : (v || '—'),
      cellClass: () => 'text-zinc-500 truncate' },
    { key: 'timestamp',        label: 'Time',   align: 'right', width: 'w-14',
      render: formatTime, cellClass: () => 'text-zinc-500' },
  ],
});

// ───── SCAN (raw scanner alerts today) ───────────────────────────────

export const scanStageConfig = ({ scanCount }) => ({
  title: 'Scanner Alerts Today',
  versionTag: 'v19.31.10',
  defaultSortKey: 'timestamp',
  emptyText: 'No scanner alerts yet.',
  filters: [
    { key: 'tier',       label: 'Tier',  values: 'auto', sort: sortTier },
    { key: 'setup_type', label: 'Setup', values: 'auto', format: humanizeSetup, maxValues: 6 },
    { key: 'phase',      label: 'Phase', values: 'auto', format: (v) => v || '?' },
  ],
  headerExtras: (
    <span className="v5-mono text-[11px] text-zinc-500">{scanCount} hits</span>
  ),
  columns: [
    { key: 'symbol',     label: 'Sym',     align: 'left',  width: 'w-14',
      cellClass: () => 'font-bold text-zinc-100' },
    { key: 'tier',       label: 'Tier',    align: 'left',  width: 'w-12',
      cellClass: () => 'text-zinc-500' },
    { key: 'setup_type', label: 'Setup',   align: 'left',  width: 'w-24',
      render: (v) => v ? String(v).replace(/_/g, ' ').slice(0, 22) : '—',
      cellClass: () => 'text-zinc-400 truncate' },
    { key: 'gate_score', label: 'Gate',    align: 'right', width: 'w-12',
      render: (v) => v != null ? Number(v).toFixed(0) : '—',
      cellClass: (v) => (Number(v) >= 60 ? 'text-emerald-400 font-semibold' : 'text-zinc-400') },
    { key: 'price',      label: 'Px',      align: 'right', width: 'w-16',
      render: formatPrice, cellClass: () => 'text-zinc-400' },
    { key: 'change_pct', label: 'Δ',       align: 'right', width: 'w-14',
      render: (v) => formatPct(v),
      cellClass: (v) => ((Number(v) || 0) >= 0 ? 'text-emerald-400' : 'text-rose-400') },
    { key: 'phase',      label: 'Phase',   align: 'left',  width: 'w-16',
      cellClass: () => 'text-zinc-500' },
    { key: 'timestamp',  label: 'Time',    align: 'right', width: 'w-14',
      render: formatTime, cellClass: () => 'text-zinc-500' },
  ],
});
;
