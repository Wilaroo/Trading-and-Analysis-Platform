/**
 * V5 Briefings panel — morning prep / mid-day recap / power hour / close recap,
 * matching option-1-v5-command-center.html.
 *
 * Only the "morning" briefing is currently sourced from real data (the
 * `context` hook). The others are rendered as scheduled placeholders — one
 * row each — so the UI matches the mockup structure without inventing fake
 * data.
 */
import React from 'react';

const nowET = () => new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });

const timeUntil = (hh, mm) => {
  const now = new Date();
  const target = new Date();
  target.setHours(hh, mm, 0, 0);
  let diff = target - now;
  if (diff < 0) return 'passed';
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  return h > 0 ? `in ${h}h ${m}m` : `in ${m}m`;
};

const MorningPrep = ({ context }) => {
  if (!context) return null;
  const regime = context.regime || context.market_regime;
  const vix = context.vix;
  const news = context.news_flow || context.news || [];
  return (
    <div className="v5-briefing-card v5-briefing-new">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="v5-mono font-bold text-xs text-violet-400">MORNING PREP</span>
          <span className="v5-chip v5-chip-manage">AUTO</span>
        </div>
        <span className="v5-mono text-[9px] v5-dim">{context.prep_time || '09:28'}</span>
      </div>
      <div className="v5-why mt-1">
        {regime && <span className="text-zinc-200 font-semibold">{regime}</span>}
        {vix != null && <span> · VIX {Number(vix).toFixed(1)}</span>}
        {news.length > 0 && (
          <span>. {news.slice(0, 3).map((n) => n.headline || n.text || n).join(', ')}.</span>
        )}
        {!regime && !vix && news.length === 0 && (
          <span className="text-zinc-500">Waiting for pre-market context signals...</span>
        )}
      </div>
    </div>
  );
};

const MidDayRecap = ({ positions, totalPnl }) => {
  const wins = (positions || []).filter(p => (p.r_multiple ?? p.pnl_r ?? 0) > 0).length;
  const losses = (positions || []).filter(p => (p.r_multiple ?? p.pnl_r ?? 0) < 0).length;
  const now = nowET();
  return (
    <div className="v5-briefing-card">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="v5-mono font-bold text-xs text-amber-400">MID-DAY RECAP</span>
          {(wins + losses) > 0 && <span className="v5-chip v5-chip-manage">LIVE</span>}
        </div>
        <span className="v5-mono text-[9px] v5-dim">{now}</span>
      </div>
      <div className="v5-why mt-1">
        {(wins + losses) > 0
          ? `${wins} wins · ${losses} losses · ${totalPnl >= 0 ? '+$' : '−$'}${Math.abs(totalPnl || 0).toFixed(0)} day P&L.`
          : <span className="text-zinc-500">No fills yet today.</span>
        }
      </div>
    </div>
  );
};

const PendingCard = ({ title, targetTime }) => (
  <div className="v5-briefing-card v5-briefing-pending">
    <div className="flex items-center justify-between">
      <div className="v5-mono font-bold text-xs text-zinc-400">{title}</div>
      <span className="v5-mono text-[9px]">{targetTime}</span>
    </div>
    <div className="v5-why mt-1">pending · auto-generates at {title.includes('POWER') ? '15:00' : '16:00'}</div>
  </div>
);

export const BriefingsV5 = ({ context, positions, totalPnl }) => {
  return (
    <div data-testid="v5-briefings" className="flex flex-col">
      <MorningPrep context={context} />
      <MidDayRecap positions={positions} totalPnl={totalPnl} />
      <PendingCard title="POWER HOUR" targetTime={timeUntil(15, 0)} />
      <PendingCard title="CLOSE RECAP" targetTime={timeUntil(16, 0)} />
    </div>
  );
};

export default BriefingsV5;
