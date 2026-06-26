/**
 * RiskRail — V6 §4 left-edge "DLP" rail (Daily-Loss-Protection headroom).
 *
 * A vertical bar that fills from the bottom with the % of the daily-loss budget
 * still UNUSED (from /api/safety/risk-rail, which mirrors the kill-switch math).
 * Emerald (healthy) → amber (<50%) → rose (<20% or kill-switch tripped). The
 * tooltip carries today's P&L vs the effective limit. Compact (46px) column.
 */
import React from 'react';
import { useRiskRail } from '../hooks/useRiskRail';

const colorFor = (headroom, ks) => {
  if (ks || headroom <= 0) return '#fb7185';   // rose
  if (headroom < 20) return '#fb7185';
  if (headroom < 50) return '#fbbf24';          // amber
  return '#34d399';                             // emerald
};

const fmtUsd = (v) =>
  (v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`);

export const RiskRail = () => {
  const { data } = useRiskRail();
  const headroom = data?.headroom_pct ?? 100;
  const ks = !!data?.kill_switch_active;
  const color = colorFor(headroom, ks);
  const fillH = Math.max(2, Math.min(100, headroom));
  const title = data
    ? `Daily-Loss Protection\nToday P&L: ${fmtUsd(data.daily_pnl)} (realized ${fmtUsd(data.realized)} + unrealized ${fmtUsd(data.unrealized)})\nLimit: ${fmtUsd(data.effective_limit)} · used ${data.used_pct}%\nHeadroom: ${data.headroom_pct}%${ks ? '\nKILL-SWITCH TRIPPED' : ''}${data.awaiting_quotes ? '\n(awaiting quotes — unrealized excluded)' : ''}`
    : 'Daily-Loss Protection';

  return (
    <div
      data-testid="v6-risk-rail"
      data-headroom={Math.round(headroom)}
      data-killswitch={ks ? '1' : '0'}
      className="rounded-md border border-white/10 bg-white/[0.02] flex flex-col items-center py-3 min-h-[420px]"
      style={{ width: '46px', flexShrink: 0 }}
      title={title}
    >
      <div className="text-[9px] uppercase tracking-widest text-zinc-500 mb-3">DLP</div>
      <div className="relative flex-1 w-2.5 rounded-full bg-white/[0.06] overflow-hidden">
        <div
          className="absolute bottom-0 inset-x-0 rounded-full transition-all duration-700 ease-out"
          style={{ height: `${fillH}%`, backgroundColor: color, boxShadow: `0 0 10px ${color}` }}
        />
      </div>
      <div className="text-[10px] font-mono mt-3 font-bold" style={{ color }} data-testid="v6-risk-rail-pct">
        {Math.round(headroom)}%
      </div>
      {ks && (
        <div className="text-[8px] text-rose-400 uppercase mt-1 text-center leading-tight font-bold" data-testid="v6-risk-rail-ks">
          kill<br />switch
        </div>
      )}
    </div>
  );
};

export default RiskRail;
