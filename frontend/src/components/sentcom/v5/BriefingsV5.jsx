/**
 * V5 Briefings panel — morning prep / mid-day recap / power hour / close recap,
 * matching option-1-v5-command-center.html but wired to real data.
 *
 * MORNING PREP is hydrated from `useMorningBriefing` (gameplan + DRC + scanner
 * + bot endpoints). The other three rows cycle through "active" / "pending"
 * / "passed" based on the current US market time.
 *
 * Click a briefing card → an inline expand shows the full detail below the
 * card so the user never has to leave the V5 grid. The legacy modal still
 * exists for deep dives but is no longer an auto-popup.
 */
import React, { useMemo, useState } from 'react';
import { useMorningBriefing } from './useMorningBriefing';
import { useMarketState } from '../../../contexts';
import { fmtET12 } from '../../../utils/timeET';
import { WeekendBriefingCard } from './WeekendBriefingCard';

// 24h "HH:MM" string in ET — kept for internal math (split by ':' for minutes-of-day).
const nowET = () => {
  return new Date().toLocaleTimeString('en-US', {
    hour12: false, hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York',
  });
};

// 12-hour ET label for user-facing display ("9:30 AM").
const nowETDisplay = () => fmtET12(new Date());

const minutesET = () => {
  const [h, m] = nowET().split(':').map(Number);
  return h * 60 + m;
};

const statusFor = (windowStart, windowEnd) => {
  const n = minutesET();
  if (n < windowStart) return 'pending';
  if (n >= windowStart && n < windowEnd) return 'active';
  return 'passed';
};

const formatTimeRange = (startHH, startMM) => {
  // Render "9:30 AM ET" / "11:30 AM ET" / "3:00 PM ET" — ET 12-hour.
  const today = new Date();
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate(), startHH, startMM);
  // Build the label in ET to be safe across observer timezones.
  const label = d.toLocaleTimeString('en-US', {
    timeZone: 'America/New_York',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
  return `${label} ET`;
};


/* ── Cards ────────────────────────────────────────────────────────────── */

/** Inline clickable ticker symbol — used inside briefing detail rows. */
const ClickableSymbol = ({ symbol, onSymbolClick, className = '' }) => {
  if (!symbol) return null;
  const sym = String(symbol).toUpperCase();
  if (!onSymbolClick) return <span className={className}>{sym}</span>;
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onSymbolClick(sym); }}
      className={`hover:text-cyan-300 hover:underline transition-colors cursor-pointer ${className}`}
      data-testid={`briefing-symbol-${sym}`}
      title={`Open ${sym} analysis`}
    >
      {sym}
    </button>
  );
};


const MorningPrepCard = ({ data, loading, expanded, onToggle, onSymbolClick, onOpenDeepDive }) => {
  const gp = data?.game_plan;
  const drc = data?.drc;
  const scanner = data?.scanner;
  const bot = data?.bot;

  // Window: 08:00 ET → 09:30 ET (pre-market prep)
  const state = statusFor(8 * 60, 9.5 * 60);

  // Fallback: backend gameplan service stores regime in big_picture.market_regime
  // — read both shapes so the card hydrates even when only one is populated.
  const regime = gp?.regime || gp?.market_regime || gp?.big_picture?.market_regime || scanner?.regime;
  const bias = gp?.bias || gp?.market_bias || gp?.big_picture?.bias;
  const watch = gp?.watchlist || gp?.symbols || (Array.isArray(gp?.stocks_in_play) ? gp.stocks_in_play.map(s => s?.symbol).filter(Boolean) : []);
  const maxRisk = drc?.max_daily_risk ?? drc?.max_daily_r;
  const drcHealth = drc?.status || drc?.health;
  const scannerHits = scanner?.total_hits ?? scanner?.active_setups ?? 0;
  const botStatus = bot?.running ? 'ACTIVE' : 'IDLE';
  const botMode = bot?.mode || bot?.trading_phase;

  const hasData = regime || bias || watch.length > 0 || maxRisk != null || drcHealth || scannerHits > 0;

  return (
    <div
      data-testid="v5-briefing-morning"
      className={`v5-briefing-card ${state === 'active' ? 'v5-briefing-new' : ''} ${state === 'pending' ? 'v5-briefing-pending' : ''}`}
      onClick={state === 'pending' ? undefined : onToggle}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="v5-mono font-bold text-xs text-violet-400">MORNING PREP</span>
          {state === 'active' && <span className="v5-new-badge">NEW</span>}
          {state === 'passed' && <span className="v5-chip v5-chip-close">PASSED</span>}
        </div>
        <div className="flex items-center gap-2">
          {onOpenDeepDive && (
            <button
              type="button"
              data-testid="briefing-open-deep-dive"
              onClick={(e) => { e.stopPropagation(); onOpenDeepDive(); }}
              className="v5-mono text-[9px] text-zinc-500 hover:text-violet-400 transition-colors uppercase tracking-wide"
              title="Open full briefing (top movers + overnight sentiment)"
            >
              full briefing ↗
            </button>
          )}
          <span className="v5-mono text-[9px] v5-dim">{state === 'pending' ? '08:00' : '09:28'}</span>
        </div>
      </div>
      <div className="v5-why mt-1">
        {loading && !hasData && <span className="text-zinc-500">Loading...</span>}
        {!loading && !hasData && <span className="text-zinc-500">No game plan filed. Add one in your journal.</span>}
        {hasData && (
          <>
            {regime && <span className="text-zinc-200 font-semibold">{regime}</span>}
            {bias && <span>{regime ? ' · ' : ''}Bias {bias}</span>}
            {maxRisk != null && <span> · risk cap <span className="text-zinc-200">${Math.round(maxRisk)}</span></span>}
            {scannerHits > 0 && <span> · scanner {scannerHits} hits</span>}
            <span> · bot <span className={bot?.running ? 'v5-up' : 'v5-down'}>{botStatus}</span>{botMode ? ` (${botMode})` : ''}</span>
          </>
        )}
      </div>
      {expanded && hasData && (
        <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] space-y-1 text-zinc-400">
          {gp?.thesis && (
            <div><span className="text-zinc-500">Thesis: </span>{gp.thesis}</div>
          )}
          {watch.length > 0 && (
            <div>
              <span className="text-zinc-500">Watchlist: </span>
              {watch.slice(0, 8).map((w, i) => {
                const sym = typeof w === 'string' ? w : (w?.symbol || w?.ticker);
                if (!sym) return null;
                return (
                  <React.Fragment key={sym + i}>
                    {i > 0 && <span className="text-zinc-600">, </span>}
                    <ClickableSymbol symbol={sym} onSymbolClick={onSymbolClick} className="text-zinc-300 font-semibold" />
                  </React.Fragment>
                );
              })}
            </div>
          )}
          {drcHealth && (
            <div>
              <span className="text-zinc-500">DRC: </span>
              <span className={drcHealth === 'green' || drcHealth === 'healthy' ? 'v5-up' : drcHealth === 'yellow' ? 'v5-warn' : 'v5-down'}>
                {drcHealth.toUpperCase()}
              </span>
              {drc?.notes && <span> · {drc.notes}</span>}
            </div>
          )}
          {scanner?.last_scan_at && (
            <div><span className="text-zinc-500">Last scan: </span>{scanner.last_scan_at}</div>
          )}
        </div>
      )}
    </div>
  );
};


const MidDayRecapCard = ({ positions, totalPnl, briefing, expanded, onToggle, onSymbolClick, onOpenDeepDive }) => {
  const state = statusFor(11.5 * 60, 13 * 60);   // 11:30 → 13:00 ET

  const closed = useMemo(() => (positions || []).filter(p => p?.status === 'closed'), [positions]);
  const open = useMemo(() => (positions || []).filter(p => p?.status !== 'closed'), [positions]);
  const wins = closed.filter(p => (p.realized_pnl ?? p.pnl ?? 0) > 0).length;
  const losses = closed.filter(p => (p.realized_pnl ?? p.pnl ?? 0) < 0).length;

  // 2026-04-28 fallback — when no fills/positions, show scanner + regime
  // pulse instead of "No fills yet today" silence (operator-flagged).
  const scanner = briefing?.scanner;
  const gp = briefing?.game_plan;
  const regime = gp?.regime || gp?.market_regime || gp?.big_picture?.market_regime || scanner?.regime;
  const scannerHits = scanner?.total_hits ?? scanner?.active_setups ?? 0;

  return (
    <div
      data-testid="v5-briefing-midday"
      className={`v5-briefing-card ${state === 'active' ? 'v5-briefing-new' : ''} ${state === 'pending' ? 'v5-briefing-pending' : ''}`}
      onClick={state === 'pending' ? undefined : onToggle}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="v5-mono font-bold text-xs text-amber-400">MID-DAY RECAP</span>
          {state === 'active' && <span className="v5-new-badge">NEW</span>}
          {state === 'passed' && <span className="v5-chip v5-chip-close">PASSED</span>}
        </div>
        <div className="flex items-center gap-2">
          {onOpenDeepDive && state !== 'pending' && (
            <button
              type="button"
              data-testid="briefing-midday-open-deep-dive"
              onClick={(e) => { e.stopPropagation(); onOpenDeepDive('midday'); }}
              className="v5-mono text-[9px] text-zinc-500 hover:text-amber-400 transition-colors uppercase tracking-wide"
              title="Open full mid-day briefing (closed trades, open P&L, regime drift)"
            >
              full briefing ↗
            </button>
          )}
          <span className="v5-mono text-[9px] v5-dim">{state === 'pending' ? formatTimeRange(11, 30) : nowETDisplay()}</span>
        </div>
      </div>
      <div className="v5-why mt-1">
        {(closed.length === 0 && open.length === 0) ? (
          // Fallback content — regime + scanner pulse so the card is never
          // empty during the lunch lull.
          (regime || scannerHits > 0) ? (
            <>
              <span className="text-zinc-500">No fills yet · </span>
              {regime && <span className="text-zinc-200 font-semibold">{regime}</span>}
              {scannerHits > 0 && <span>{regime ? ' · ' : ''}scanner {scannerHits} hits</span>}
            </>
          ) : (
            <span className="text-zinc-500">No fills yet today.</span>
          )
        ) : (
          <>
            <span className={wins >= losses ? 'v5-up' : 'v5-down'}>{wins}W · {losses}L</span>
            {open.length > 0 && <span> · {open.length} open</span>}
            <span> · <span className={Number(totalPnl) >= 0 ? 'v5-up' : 'v5-down'}>{Number(totalPnl) >= 0 ? '+$' : '−$'}{Math.abs(Number(totalPnl) || 0).toFixed(0)}</span> day P&L</span>
          </>
        )}
      </div>
      {expanded && closed.length > 0 && (
        <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] space-y-1">
          {closed.slice(0, 5).map((p, i) => {
            const pnl = Number(p.realized_pnl ?? p.pnl ?? 0);
            return (
              <div key={p.id || p._id || i} className="flex justify-between">
                <span className="text-zinc-400">
                  <ClickableSymbol symbol={p.symbol} onSymbolClick={onSymbolClick} className="text-zinc-300" />
                  {' · '}{p.setup_type || p.strategy || '—'}
                </span>
                <span className={pnl >= 0 ? 'v5-up' : 'v5-down'}>{pnl >= 0 ? '+' : '−'}${Math.abs(pnl).toFixed(0)}</span>
              </div>
            );
          })}
        </div>
      )}
      {/* Empty-state expand: surface scanner watchlist so operator has
          something actionable to skim mid-day. */}
      {expanded && closed.length === 0 && open.length === 0 && Array.isArray(gp?.watchlist) && gp.watchlist.length > 0 && (
        <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] space-y-1 text-zinc-400">
          <div>
            <span className="text-zinc-500">Watchlist: </span>
            {gp.watchlist.slice(0, 8).map((sym, i) => (
              <React.Fragment key={sym + i}>
                {i > 0 && <span className="text-zinc-600">, </span>}
                <ClickableSymbol symbol={sym} onSymbolClick={onSymbolClick} className="text-zinc-300 font-semibold" />
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};


const PowerHourCard = ({ positions, totalPnl, briefing, expanded, onToggle, onSymbolClick, onOpenDeepDive }) => {
  const state = statusFor(15 * 60, 15.75 * 60); // 15:00 → 15:45 ET

  const open = (positions || []).filter(p => p?.status !== 'closed');
  const atRiskCount = open.filter(p => (p.unrealized_pnl ?? p.pnl ?? 0) < 0).length;

  // 2026-04-28 fallback — when no open positions, surface the top scanner
  // watchlist names so the operator has setups to skim for the close
  // (operator-flagged: "show top movers + suggested setups").
  const gp = briefing?.game_plan;
  const scanner = briefing?.scanner;
  const fallbackWatch = (Array.isArray(gp?.watchlist) ? gp.watchlist : [])
    .filter(Boolean).slice(0, 5);
  const scannerHits = scanner?.total_hits ?? scanner?.active_setups ?? 0;

  return (
    <div
      data-testid="v5-briefing-powerhour"
      className={`v5-briefing-card ${state === 'active' ? 'v5-briefing-new' : ''} ${state === 'pending' ? 'v5-briefing-pending' : ''}`}
      onClick={state === 'pending' ? undefined : onToggle}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="v5-mono font-bold text-xs text-orange-400">POWER HOUR</span>
          {state === 'active' && <span className="v5-new-badge">NEW</span>}
          {state === 'passed' && <span className="v5-chip v5-chip-close">PASSED</span>}
        </div>
        <div className="flex items-center gap-2">
          {onOpenDeepDive && state !== 'pending' && (
            <button
              type="button"
              data-testid="briefing-powerhour-open-deep-dive"
              onClick={(e) => { e.stopPropagation(); onOpenDeepDive('powerhour'); }}
              className="v5-mono text-[9px] text-zinc-500 hover:text-orange-400 transition-colors uppercase tracking-wide"
              title="Open full power-hour briefing (open positions + setups for the close)"
            >
              full briefing ↗
            </button>
          )}
          <span className="v5-mono text-[9px] v5-dim">{state === 'pending' ? formatTimeRange(15, 0) : nowETDisplay()}</span>
        </div>
      </div>
      <div className="v5-why mt-1">
        {open.length === 0 ? (
          fallbackWatch.length > 0 || scannerHits > 0 ? (
            <>
              <span className="text-zinc-500">Flat into close · </span>
              {scannerHits > 0 && <span>scanner {scannerHits} hits</span>}
              {fallbackWatch.length > 0 && (
                <span>{scannerHits > 0 ? ' · watch ' : 'watch '}
                  {fallbackWatch.slice(0, 3).map((sym, i) => (
                    <React.Fragment key={sym + i}>
                      {i > 0 && <span className="text-zinc-600">, </span>}
                      <ClickableSymbol symbol={sym} onSymbolClick={onSymbolClick} className="text-zinc-300 font-semibold" />
                    </React.Fragment>
                  ))}
                </span>
              )}
            </>
          ) : (
            <span className="text-zinc-500">No open positions heading into close.</span>
          )
        ) : (
          <>
            <span>{open.length} open</span>
            {atRiskCount > 0 && <span> · <span className="v5-warn">{atRiskCount} underwater</span></span>}
            <span> · <span className={Number(totalPnl) >= 0 ? 'v5-up' : 'v5-down'}>{Number(totalPnl) >= 0 ? '+$' : '−$'}{Math.abs(Number(totalPnl) || 0).toFixed(0)}</span></span>
          </>
        )}
      </div>
      {expanded && open.length > 0 && (
        <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] space-y-1">
          {open.map((p, i) => {
            const pnl = Number(p.unrealized_pnl ?? p.pnl ?? 0);
            return (
              <div key={p.id || p._id || i} className="flex justify-between">
                <span className="text-zinc-400">
                  <ClickableSymbol symbol={p.symbol} onSymbolClick={onSymbolClick} className="text-zinc-300" />
                </span>
                <span className={pnl >= 0 ? 'v5-up' : 'v5-down'}>{pnl >= 0 ? '+' : '−'}${Math.abs(pnl).toFixed(0)}</span>
              </div>
            );
          })}
        </div>
      )}
      {/* Empty-state expand: full watchlist for the close. */}
      {expanded && open.length === 0 && fallbackWatch.length > 0 && (
        <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] space-y-1 text-zinc-400">
          <div>
            <span className="text-zinc-500">Setups for the close: </span>
            {fallbackWatch.map((sym, i) => (
              <React.Fragment key={sym + i}>
                {i > 0 && <span className="text-zinc-600">, </span>}
                <ClickableSymbol symbol={sym} onSymbolClick={onSymbolClick} className="text-zinc-300 font-semibold" />
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};


const CloseRecapCard = ({ positions, totalPnl, expanded, onToggle, onSymbolClick, onOpenDeepDive }) => {
  const state = statusFor(16 * 60, 16.5 * 60); // 16:00 → 16:30 ET

  const closed = useMemo(() => (positions || []).filter(p => p?.status === 'closed'), [positions]);
  const wins = closed.filter(p => (p.realized_pnl ?? p.pnl ?? 0) > 0).length;
  const losses = closed.filter(p => (p.realized_pnl ?? p.pnl ?? 0) < 0).length;
  const winRate = closed.length ? wins / closed.length : null;

  return (
    <div
      data-testid="v5-briefing-close"
      className={`v5-briefing-card ${state === 'active' ? 'v5-briefing-new' : ''} ${state === 'pending' ? 'v5-briefing-pending' : ''}`}
      onClick={state === 'pending' ? undefined : onToggle}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="v5-mono font-bold text-xs text-slate-300">CLOSE RECAP</span>
          {state === 'active' && <span className="v5-chip v5-chip-manage">LIVE</span>}
          {state === 'passed' && <span className="v5-chip v5-chip-close">DONE</span>}
        </div>
        <div className="flex items-center gap-2">
          {onOpenDeepDive && state !== 'pending' && (
            <button
              type="button"
              data-testid="briefing-close-open-deep-dive"
              onClick={(e) => { e.stopPropagation(); onOpenDeepDive('close'); }}
              className="v5-mono text-[9px] text-zinc-500 hover:text-slate-300 transition-colors uppercase tracking-wide"
              title="Open full close recap (every fill, win-rate, day P&L breakdown)"
            >
              full briefing ↗
            </button>
          )}
          <span className="v5-mono text-[9px] v5-dim">{state === 'pending' ? formatTimeRange(16, 0) : nowETDisplay()}</span>
        </div>
      </div>
      <div className="v5-why mt-1">
        {closed.length === 0 ? (
          <span className="text-zinc-500">{state === 'pending' ? 'recap will auto-generate at 16:00' : 'No trades to recap.'}</span>
        ) : (
          <>
            <span>{wins}W · {losses}L</span>
            {winRate != null && <span> · {(winRate * 100).toFixed(0)}% WR</span>}
            <span> · <span className={Number(totalPnl) >= 0 ? 'v5-up' : 'v5-down'}>{Number(totalPnl) >= 0 ? '+$' : '−$'}{Math.abs(Number(totalPnl) || 0).toFixed(0)}</span></span>
          </>
        )}
      </div>
      {expanded && closed.length > 0 && (
        <div className="mt-2 pt-2 border-t border-zinc-800 text-[10px] space-y-1 max-h-32 overflow-y-auto v5-scroll">
          {closed.map((p, i) => {
            const pnl = Number(p.realized_pnl ?? p.pnl ?? 0);
            return (
              <div key={p.id || p._id || i} className="flex justify-between">
                <span className="text-zinc-400">
                  <ClickableSymbol symbol={p.symbol} onSymbolClick={onSymbolClick} className="text-zinc-300" />
                  {' · '}{p.setup_type || '—'}
                </span>
                <span className={pnl >= 0 ? 'v5-up' : 'v5-down'}>{pnl >= 0 ? '+' : '−'}${Math.abs(pnl).toFixed(0)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};


export const BriefingsV5 = ({ context, positions, totalPnl, onSymbolClick, onOpenDeepDive }) => {
  const { loading, data } = useMorningBriefing({ refreshMs: 120_000 });
  const [expandedKey, setExpandedKey] = useState('morning');
  const toggle = (key) => setExpandedKey(curr => curr === key ? null : key);
  // Surface the Weekend Briefing on Sat/Sun (canonical state from the
  // shared MarketStateContext — same source as the wordmark moon).
  // We render it FIRST in the panel during the weekend so the operator
  // sees the week-ahead read before the (idle) morning prep card.
  const marketState = useMarketState();
  const isWeekend = marketState?.is_weekend === true;

  // Use `context` as a secondary source if briefing endpoints are unavailable
  const briefing = data || {
    game_plan: context?.game_plan,
    drc: context?.drc,
    scanner: context?.scanner,
    bot: context?.bot,
  };

  return (
    <div data-testid="v5-briefings" data-help-id="briefings" className="flex flex-col">
      {isWeekend && <WeekendBriefingCard onSymbolClick={onSymbolClick} />}
      <MorningPrepCard
        data={briefing}
        loading={loading}
        expanded={expandedKey === 'morning'}
        onToggle={() => toggle('morning')}
        onSymbolClick={onSymbolClick}
        onOpenDeepDive={onOpenDeepDive}
      />
      <MidDayRecapCard
        positions={positions}
        totalPnl={totalPnl}
        briefing={briefing}
        expanded={expandedKey === 'midday'}
        onToggle={() => toggle('midday')}
        onSymbolClick={onSymbolClick}
        onOpenDeepDive={onOpenDeepDive}
      />
      <PowerHourCard
        positions={positions}
        totalPnl={totalPnl}
        briefing={briefing}
        expanded={expandedKey === 'powerhour'}
        onToggle={() => toggle('powerhour')}
        onSymbolClick={onSymbolClick}
        onOpenDeepDive={onOpenDeepDive}
      />
      <CloseRecapCard
        positions={positions}
        totalPnl={totalPnl}
        expanded={expandedKey === 'close'}
        onToggle={() => toggle('close')}
        onSymbolClick={onSymbolClick}
        onOpenDeepDive={onOpenDeepDive}
      />
    </div>
  );
};

export default BriefingsV5;
