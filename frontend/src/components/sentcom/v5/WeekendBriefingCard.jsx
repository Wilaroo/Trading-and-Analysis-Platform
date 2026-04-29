/**
 * WeekendBriefingCard — Sunday-afternoon weekly report.
 *
 * Surfaces the seven sections produced by the backend
 * `/api/briefings/weekend/latest` endpoint:
 *   1. Last Week Recap    — sector ETF returns + closed P&L
 *   2. Major News          — top headlines from past 7 days
 *   3. Earnings Calendar   — companies reporting next 5 trading days
 *   4. Macro Calendar      — high/medium-impact US events
 *   5. Sector Catalysts    — IPOs + FDA + conferences from news scan
 *   6. Bot's Gameplan      — LLM-synthesized thesis paragraph
 *   7. Risk Map            — landmines (earnings on held positions, etc)
 *
 * All ticker symbols use `<ClickableSymbol>` so clicks open the existing
 * enhanced ticker modal (`onSymbolClick={handleOpenTicker}` flows in
 * from `SentComV5View`).
 *
 * Render gating: the card only mounts inside BriefingsV5 when the
 * canonical market state is `weekend` (single source of truth via
 * `useMarketState()` — same hook driving the wordmark moon + chip moon).
 * Mon-Fri the card stays out of the way. The "Regenerate" button always
 * works regardless of state so the operator can refresh on-demand.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Calendar, AlertTriangle, RefreshCw, Newspaper, TrendingUp, Trophy } from 'lucide-react';
import { readAutoLoadedSymbol } from '../../../hooks/useMondayMorningAutoLoad';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtDate = (iso) => {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  } catch { return iso; }
};

const fmtPctSigned = (n) => {
  if (n == null || isNaN(n)) return '—';
  const v = Number(n);
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
};

/** Inline clickable ticker — mirrors BriefingsV5.ClickableSymbol so
 *  hovering + click behaviour is consistent across the briefings panel. */
const ClickableSymbol = ({ symbol, onSymbolClick, className = '' }) => {
  if (!symbol) return null;
  const sym = String(symbol).toUpperCase();
  if (!onSymbolClick) return <span className={className}>{sym}</span>;
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onSymbolClick(sym); }}
      className={`hover:text-cyan-300 hover:underline transition-colors cursor-pointer ${className}`}
      data-testid={`weekend-briefing-symbol-${sym}`}
      title={`Open ${sym} analysis`}
    >
      {sym}
    </button>
  );
};


const Section = ({ title, icon: Icon, count, children, defaultOpen = false }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-zinc-800/60 first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-900/40 transition-colors"
        data-testid={`weekend-section-toggle-${title.replace(/\s+/g, '-').toLowerCase()}`}
      >
        {open ? <ChevronDown className="w-3 h-3 text-zinc-500" /> : <ChevronRight className="w-3 h-3 text-zinc-500" />}
        {Icon && <Icon className="w-3 h-3 text-zinc-400" />}
        <span className="v5-mono text-[12px] uppercase tracking-wider text-zinc-300 font-bold">{title}</span>
        {count != null && (
          <span className="v5-mono text-[11px] text-zinc-500 ml-auto">
            {count}
          </span>
        )}
      </button>
      {open && (
        <div className="px-3 pb-3 v5-mono text-[12px] text-zinc-300/90">
          {children}
        </div>
      )}
    </div>
  );
};


/* ── Section renderers ─────────────────────────────────────────────── */

const LastWeekRecap = ({ data, onSymbolClick }) => {
  const sectors = data?.sectors || [];
  const trades = data?.closed_trades || [];
  const summary = data?.closed_summary || {};
  const recap = data?.gameplan_recap;
  const recapWatches = recap?.watches || [];
  const recapSummary = recap?.summary || {};
  if (!sectors.length && !trades.length && !recapWatches.length) {
    return <div className="text-zinc-600">No data — IB historical or trade history unavailable.</div>;
  }
  return (
    <div className="space-y-3">
      {recapWatches.length > 0 && (
        <div data-testid="gameplan-recap">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1">
            last week's gameplan grade
            {recap?.iso_week && <span className="ml-1 text-zinc-600">· {recap.iso_week}</span>}
          </div>
          <div className="text-[12px] mb-1.5">
            {recapSummary.wins ?? 0}W · {recapSummary.losses ?? 0}L
            {recapSummary.avg_change_pct != null && (
              <span className={` · ${recapSummary.avg_change_pct >= 0 ? 'v5-up' : 'v5-down'}`}>
                {' · '}avg {fmtPctSigned(recapSummary.avg_change_pct)}
              </span>
            )}
          </div>
          <div className="space-y-0.5">
            {recapWatches.map((w, i) => (
              <div key={`recap-${w.symbol}-${i}`} className="flex justify-between gap-2">
                <span className="truncate">
                  <ClickableSymbol symbol={w.symbol} onSymbolClick={onSymbolClick} className="text-zinc-200 font-medium" />
                  {w.thesis && (
                    <span className="ml-1.5 text-zinc-500 text-[11px] truncate">
                      {w.thesis}
                    </span>
                  )}
                </span>
                <span className={
                  w.change_pct == null
                    ? 'text-zinc-600'
                    : w.change_pct >= 0 ? 'v5-up' : 'v5-down'
                }>
                  {w.change_pct == null ? '—' : fmtPctSigned(w.change_pct)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {sectors.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1">sector returns (7d)</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            {sectors.slice(0, 11).map((s) => (
              <div key={s.symbol} className="flex justify-between">
                <span>
                  <ClickableSymbol symbol={s.symbol} onSymbolClick={onSymbolClick} className="text-zinc-200" />
                  <span className="ml-1.5 text-zinc-500 text-[11px]">{s.name}</span>
                </span>
                <span className={(s.change_pct || 0) >= 0 ? 'v5-up' : 'v5-down'}>
                  {fmtPctSigned(s.change_pct)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {trades.length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1">your closed trades (7d)</div>
          <div className="text-[12px] mb-1.5">
            {summary.wins ?? 0}W · {summary.losses ?? 0}L
            {summary.win_rate != null && <span> · {(summary.win_rate * 100).toFixed(0)}% WR</span>}
            {summary.total_pnl != null && (
              <span className={` · ${summary.total_pnl >= 0 ? 'v5-up' : 'v5-down'}`}>
                {' · '}{summary.total_pnl >= 0 ? '+' : '−'}${Math.abs(summary.total_pnl).toFixed(0)}
              </span>
            )}
          </div>
          <div className="max-h-32 overflow-y-auto v5-scroll space-y-0.5">
            {trades.map((t, i) => (
              <div key={i} className="flex justify-between">
                <span>
                  <ClickableSymbol symbol={t.symbol} onSymbolClick={onSymbolClick} className="text-zinc-200" />
                  <span className="ml-1.5 text-zinc-500">{t.setup || '—'}</span>
                </span>
                <span className={t.pnl >= 0 ? 'v5-up' : 'v5-down'}>
                  {t.pnl >= 0 ? '+' : '−'}${Math.abs(t.pnl).toFixed(0)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};


const NewsList = ({ items }) => {
  if (!items?.length) return <div className="text-zinc-600">No news — Finnhub unavailable or empty.</div>;
  return (
    <div className="space-y-1.5 max-h-48 overflow-y-auto v5-scroll">
      {items.slice(0, 12).map((n, i) => (
        <div key={i} className="leading-snug">
          <a
            href={n.url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => { if (!n.url) e.preventDefault(); }}
            className="text-zinc-300 hover:text-cyan-300 hover:underline"
          >
            {n.headline || '(no headline)'}
          </a>
          <span className="text-zinc-600 text-[11px] ml-1.5">— {n.source || '?'}</span>
        </div>
      ))}
    </div>
  );
};


const EarningsList = ({ items, onSymbolClick }) => {
  if (!items?.length) return <div className="text-zinc-600">No earnings in the next 5 trading days.</div>;
  // Group by date.
  const groups = {};
  for (const e of items) {
    const d = e.date || 'TBD';
    (groups[d] = groups[d] || []).push(e);
  }
  const sortedDates = Object.keys(groups).sort();
  return (
    <div className="space-y-2">
      {sortedDates.map((d) => (
        <div key={d}>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-0.5">{fmtDate(d)}</div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
            {groups[d].map((e, i) => (
              <div key={i} className="flex items-center justify-between">
                <ClickableSymbol symbol={e.symbol} onSymbolClick={onSymbolClick} className="text-zinc-200 font-medium" />
                <span className="text-zinc-500 text-[11px]">{e.timing || 'TBD'}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};


const MacroList = ({ items }) => {
  if (!items?.length) return <div className="text-zinc-600">No high-impact US macro events in the window.</div>;
  return (
    <div className="space-y-1 max-h-40 overflow-y-auto v5-scroll">
      {items.map((m, i) => (
        <div key={i} className="flex justify-between gap-2">
          <span className="truncate">
            <span className={m.impact === 'high' ? 'text-rose-400' : 'text-amber-400'}>●</span>
            <span className="ml-1.5 text-zinc-300">{m.event || '—'}</span>
          </span>
          <span className="text-zinc-500 tabular-nums whitespace-nowrap">{m.time || '—'}</span>
        </div>
      ))}
    </div>
  );
};


const RiskMap = ({ items, onSymbolClick }) => {
  if (!items?.length) return <div className="text-zinc-600">No flagged landmines this week.</div>;
  return (
    <div className="space-y-1.5 max-h-40 overflow-y-auto v5-scroll">
      {items.map((r, i) => {
        const dot = r.severity === 'high' ? 'bg-rose-400' :
                    r.severity === 'medium' ? 'bg-amber-400' : 'bg-zinc-500';
        return (
          <div key={i} className="flex items-start gap-2 leading-snug">
            <span className={`w-1.5 h-1.5 rounded-full mt-1 shrink-0 ${dot}`} />
            <div className="flex-1">
              {r.symbol && (
                <ClickableSymbol symbol={r.symbol} onSymbolClick={onSymbolClick} className="text-zinc-200 font-medium" />
              )}
              <span className={r.symbol ? 'ml-1.5' : ''}>{r.detail}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};


const Catalysts = ({ items }) => {
  if (!items?.length) return <div className="text-zinc-600">No catalyst-keyword headlines surfaced.</div>;
  return (
    <div className="space-y-1.5 max-h-40 overflow-y-auto v5-scroll">
      {items.map((c, i) => (
        <div key={i} className="leading-snug">
          <a
            href={c.url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => { if (!c.url) e.preventDefault(); }}
            className="text-zinc-300 hover:text-cyan-300 hover:underline"
          >
            {c.headline}
          </a>
          {c.matched_keywords?.length > 0 && (
            <span className="ml-1.5 text-amber-400/70 text-[11px] uppercase tracking-wider">
              [{c.matched_keywords.join(', ')}]
            </span>
          )}
        </div>
      ))}
    </div>
  );
};


/**
 * GameplanBlock — renders the LLM-synthesized weekly thesis.
 *
 * Backend may return either:
 *   - A structured object: `{ text: string, watches: [{symbol, thesis,
 *     key_level, invalidation}] }` — preferred new shape.
 *   - A legacy string: from older cached docs before the JSON-mode
 *     migration. Rendered as a single paragraph block.
 *
 * Watches are clickable cards — click the ticker to open the existing
 * enhanced ticker modal (same `onSymbolClick` handler that flows in
 * from `SentComV5View`).
 */
const GameplanBlock = ({ gameplan, onSymbolClick, isoWeek }) => {
  // Empty state: nothing returned from the backend at all.
  if (!gameplan || (typeof gameplan === 'string' && !gameplan.trim())) {
    return <div className="text-zinc-600">Gameplan synthesis skipped (LLM unavailable).</div>;
  }
  // Legacy string shape — render as a single paragraph block.
  if (typeof gameplan === 'string') {
    return (
      <div className="whitespace-pre-wrap leading-snug text-[12px] text-zinc-300">
        {gameplan}
      </div>
    );
  }

  const text = gameplan.text || '';
  const watches = Array.isArray(gameplan.watches) ? gameplan.watches : [];
  // Symbol that the Monday-morning auto-load fired on for this ISO week
  // (set by `useMondayMorningAutoLoad`). Used to render a "live now"
  // border around the matching watch card so the operator can see at a
  // glance which watch is on the chart right now.
  const autoLoadedSymbol = readAutoLoadedSymbol(isoWeek);

  return (
    <div className="space-y-3">
      {watches.length > 0 && (
        <div data-testid="gameplan-watches">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1.5">
            top {watches.length} watch{watches.length === 1 ? '' : 'es'}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {watches.map((w, i) => {
              const isLive = autoLoadedSymbol && w.symbol === autoLoadedSymbol;
              return (
                <div
                  key={`${w.symbol}-${i}`}
                  data-testid={`gameplan-watch-${w.symbol}`}
                  data-live={isLive ? 'true' : 'false'}
                  className={`rounded border px-2 py-1.5 transition-colors ${
                    isLive
                      ? 'border-cyan-400/60 bg-cyan-900/10 hover:border-cyan-300'
                      : 'border-zinc-800 bg-zinc-900/40 hover:border-cyan-500/40'
                  }`}
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <div className="flex items-center gap-1.5">
                      <ClickableSymbol
                        symbol={w.symbol}
                        onSymbolClick={onSymbolClick}
                        className="text-zinc-100 font-bold text-[13px]"
                      />
                      {isLive && (
                        <span
                          className="v5-mono text-[8px] uppercase tracking-wider text-cyan-300 px-1 rounded bg-cyan-500/15 border border-cyan-500/30"
                          title="Auto-framed on the chart by the Monday 09:25 ET hook"
                        >
                          LIVE
                        </span>
                      )}
                    </div>
                    {w.key_level && (
                      <span
                        className="text-cyan-400 text-[11px] tabular-nums truncate max-w-[60%]"
                        title={w.key_level}
                      >
                        {w.key_level}
                      </span>
                    )}
                  </div>
                  {w.thesis && (
                    <div className="text-zinc-300 text-[12px] leading-snug">{w.thesis}</div>
                  )}
                  {w.invalidation && (
                    <div className="text-rose-400/80 text-[11px] leading-snug mt-0.5">
                      × {w.invalidation}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
      {text && (
        <div className="whitespace-pre-wrap leading-snug text-[12px] text-zinc-300">
          {text}
        </div>
      )}
      {!text && watches.length === 0 && (
        <div className="text-zinc-600">Gameplan synthesis skipped (LLM unavailable).</div>
      )}
    </div>
  );
};


/* ── Main card ─────────────────────────────────────────────────────── */

export const WeekendBriefingCard = ({ onSymbolClick }) => {
  const [briefing, setBriefing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [err, setErr] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const resp = await fetch(`${BACKEND_URL}/api/briefings/weekend/latest`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (json?.success) setBriefing(json.briefing || null);
      else setErr(json?.error || 'Backend declined');
    } catch (e) {
      setErr(e?.message || 'Fetch failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const regenerate = useCallback(async () => {
    setGenerating(true);
    setErr(null);
    try {
      const resp = await fetch(
        `${BACKEND_URL}/api/briefings/weekend/generate?force=1`,
        { method: 'POST' }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (json?.success && json.briefing) {
        setBriefing(json.briefing);
      } else {
        setErr(json?.error || 'Generation failed');
      }
    } catch (e) {
      setErr(e?.message || 'Regenerate failed');
    } finally {
      setGenerating(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const isoWeek = briefing?.iso_week;
  const generatedAt = briefing?.generated_at;
  const sources = briefing?.sources || {};
  const generatedAtLabel = generatedAt
    ? new Date(generatedAt).toLocaleString('en-US',
        { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div
      data-testid="weekend-briefing-card"
      className="border-b border-zinc-800 bg-zinc-950"
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800/60">
        <div className="flex items-center gap-2">
          <Trophy className="w-3.5 h-3.5 text-amber-400" />
          <span className="v5-mono font-bold text-xs text-amber-300">WEEK AHEAD</span>
          {isoWeek && (
            <span className="v5-mono text-[11px] text-zinc-500">{isoWeek}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {generatedAtLabel && (
            <span className="v5-mono text-[11px] text-zinc-600" title={`Generated ${generatedAt}`}>
              {generatedAtLabel}
            </span>
          )}
          <button
            type="button"
            onClick={regenerate}
            disabled={generating}
            data-testid="weekend-briefing-regenerate-btn"
            title="Regenerate now (force re-fetch + LLM synthesis)"
            className="text-zinc-500 hover:text-zinc-200 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${generating ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {err && (
        <div data-testid="weekend-briefing-error" className="px-3 py-2 v5-mono text-[12px] text-rose-400 flex items-center gap-1.5">
          <AlertTriangle className="w-3 h-3" />
          {err}
        </div>
      )}

      {loading && !briefing && (
        <div className="px-3 py-3 v5-mono text-[12px] text-zinc-600">Loading briefing…</div>
      )}

      {!loading && !briefing && !err && (
        <div className="px-3 py-3 space-y-2">
          <div className="v5-mono text-[12px] text-zinc-500">
            No briefing yet for this week. Sunday 14:00 ET cron generates it
            automatically — or click the refresh icon above to generate now.
          </div>
          <button
            type="button"
            onClick={regenerate}
            disabled={generating}
            data-testid="weekend-briefing-generate-btn"
            className="v5-mono text-[12px] uppercase tracking-wider px-2 py-1 rounded border border-amber-700/50 text-amber-300 hover:bg-amber-900/20 transition-colors disabled:opacity-50"
          >
            {generating ? 'Generating…' : 'Generate Now'}
          </button>
        </div>
      )}

      {briefing && (
        <div>
          {/* Gameplan first — most opinionated, what the operator
              actually wants to read first thing Sunday afternoon.
              Backend returns either a structured object
              ({text, watches[]}) or a legacy string (older cache). We
              normalise here so both render. */}
          <Section title="Bot's Gameplan" icon={TrendingUp} defaultOpen>
            <GameplanBlock
              gameplan={briefing.gameplan}
              onSymbolClick={onSymbolClick}
              isoWeek={isoWeek}
            />
          </Section>

          <Section title="Risk Map" icon={AlertTriangle} count={briefing.risk_map?.length}>
            <RiskMap items={briefing.risk_map} onSymbolClick={onSymbolClick} />
          </Section>

          <Section title="Earnings Calendar" icon={Calendar} count={briefing.earnings_calendar?.length}>
            <EarningsList items={briefing.earnings_calendar} onSymbolClick={onSymbolClick} />
          </Section>

          <Section title="Macro Calendar" icon={Calendar} count={briefing.macro_calendar?.length}>
            <MacroList items={briefing.macro_calendar} />
          </Section>

          <Section title="Sector Catalysts" icon={Newspaper} count={briefing.sector_catalysts?.length}>
            <Catalysts items={briefing.sector_catalysts} />
          </Section>

          <Section title="Last Week Recap" icon={TrendingUp}>
            <LastWeekRecap data={briefing.last_week_recap} onSymbolClick={onSymbolClick} />
          </Section>

          <Section title="Major News (7d)" icon={Newspaper} count={briefing.major_news?.length}>
            <NewsList items={briefing.major_news} />
          </Section>

          {/* Sources footer — operator can see what data went in. */}
          <div className="px-3 py-1.5 border-t border-zinc-800/60 v5-mono text-[8px] text-zinc-600 flex flex-wrap gap-x-2 gap-y-0.5">
            {Object.entries(sources).map(([k, v]) => (
              <span key={k} title={`${k} source`}>
                {k}=<span className={v === 'unavailable' || v === 'skipped' ? 'text-rose-400/70' : 'text-emerald-400/70'}>{v}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default WeekendBriefingCard;
