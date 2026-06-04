/**
 * BotEdgeChip — v19.34.263 (Mission Control HUD)
 *
 * Surfaces the v19.34.262 backend split between the bot's OWN trading edge
 * and human-ADOPTED (reconciled / operator-managed) positions. Pre-this the
 * HUD blended the two, so adopted P&L inflated the headline and the operator
 * could not see the bot's clean, unpolluted performance.
 *
 * Reads `bot_edge_pnl_today` / `adopted_pnl_today` (realized+unrealized) plus
 * the realized-only variants for the tooltip. Renders nothing when the split
 * is unavailable (old backend) so it degrades gracefully.
 */
const _fmt = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '$—';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '−';
  return `${sign}$${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

const _color = (v) =>
  v == null ? 'text-zinc-400' : Number(v) >= 0 ? 'text-emerald-400' : 'text-rose-400';

export const BotEdgeChip = ({
  botEdgePnlToday,
  adoptedPnlToday,
  botRealizedPnlToday,
  adoptedRealizedPnlToday,
}) => {
  // Degrade gracefully: hide entirely when neither field is present.
  if (botEdgePnlToday == null && adoptedPnlToday == null) return null;

  const hasAdopted = adoptedPnlToday != null && Math.abs(Number(adoptedPnlToday)) > 0.005;

  return (
    <div
      data-testid="bot-edge-chip"
      className="flex items-baseline gap-2 text-[11px] v5-mono"
      title={
        `Bot Edge vs Adopted (today)\n` +
        `  Bot edge (own entries):   ${_fmt(botEdgePnlToday)}` +
        (botRealizedPnlToday != null ? `  (R ${_fmt(botRealizedPnlToday)})` : ``) + `\n` +
        `  Adopted (reconciled/op):  ${_fmt(adoptedPnlToday)}` +
        (adoptedRealizedPnlToday != null ? `  (R ${_fmt(adoptedRealizedPnlToday)})` : ``) + `\n` +
        `\nBot edge = the bot's clean trading performance. Adopted = IB orphans\n` +
        `the bot merely attributed (operator/reconciled). Kept separate so adopted\n` +
        `P&L can't inflate the bot's true edge.`
      }
    >
      <span className="uppercase tracking-wider text-zinc-500">Bot</span>
      <span data-testid="bot-edge-value" className={`font-semibold ${_color(botEdgePnlToday)}`}>
        {_fmt(botEdgePnlToday)}
      </span>
      <span className="text-zinc-700">·</span>
      <span className="uppercase tracking-wider text-zinc-500">Adopted</span>
      <span
        data-testid="adopted-pnl-value"
        className={hasAdopted ? _color(adoptedPnlToday) : 'text-zinc-600'}
      >
        {_fmt(adoptedPnlToday)}
      </span>
    </div>
  );
};

export default BotEdgeChip;
