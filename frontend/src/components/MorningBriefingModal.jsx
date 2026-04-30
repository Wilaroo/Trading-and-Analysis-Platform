/**
 * BriefingDeepDiveModal (was: MorningBriefingModal) — V5-styled deep-dive
 * surface. Accepts a `briefingKey` prop ("morning" | "midday" | "powerhour"
 * | "close") so a single component renders all four daily briefings with
 * the appropriate framing.
 *
 * Shares the `useMorningBriefing` hook with the inline V5 Briefings panel
 * so the modal and the panel never show stale/out-of-sync data.
 *
 * Visual language matches option-1-v5-command-center.html:
 *   • Pure zinc-950 background with a single 1px zinc-800 border
 *   • JetBrains Mono for numbers and labels
 *   • IBM Plex Sans for body copy
 *   • Stage chips (manage/order/eval/close/veto) reused from the V5 CSS
 *
 * 2026-04-29 wide-modal rewire: max-w bumped from `xl` (576px) to
 * min(108rem, 95vw) (~1728px on a 4K display) so the deep-dive
 * actually uses the screen real estate operators have. Also the
 * single-entry-point for all 4 briefings — clicking any pulse-button
 * in `BriefingsCompactStrip` opens this modal with the matching key.
 *
 * Backwards-compat: legacy `<MorningBriefingModal>` named import still
 * works (it's just an alias) so existing consumers that don't pass
 * a `briefingKey` keep their original "morning" rendering.
 */
import React, { memo, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, RefreshCw, Sun, Coffee, Zap, Moon } from 'lucide-react';
import { useMorningBriefing } from './sentcom/v5/useMorningBriefing';
import { useV5Styles } from './sentcom/v5/useV5Styles';
import { useBriefingLiveData } from './sentcom/v5/useBriefingLiveData';
import GamePlanStockCard from './sentcom/v5/GamePlanStockCard';
import { fmtET12 } from '../utils/timeET';

// Briefing variant table — drives header label, accent colour and icon.
// Keeping all 4 in one map means a future 5th briefing (e.g. weekly
// rollup) is a one-line addition.
const BRIEFING_VARIANTS = {
  morning: {
    label:     'MORNING BRIEFING',
    accent:    'text-violet-400',
    Icon:      Sun,
    timeBand:  '8:30 — 9:35 AM ET',
    blurb:     "Pre-open prep — game plan, watchlist, regime, risk cap.",
  },
  midday: {
    label:     'MID-DAY RECAP',
    accent:    'text-amber-400',
    Icon:      Coffee,
    timeBand:  '11:30 AM — 1:00 PM ET',
    blurb:     "Lunch checkpoint — open trades, scratched setups, drift since open.",
  },
  powerhour: {
    label:     'POWER HOUR',
    accent:    'text-orange-400',
    Icon:      Zap,
    timeBand:  '2:30 — 4:00 PM ET',
    blurb:     "Pre-close re-eval — what to manage into the bell, what to flatten.",
  },
  close: {
    label:     'EOD RECAP',
    accent:    'text-cyan-400',
    Icon:      Moon,
    timeBand:  '4:00 — 5:00 PM ET',
    blurb:     "End-of-day — closed trades, realized P&L, prediction grading.",
  },
};


const fmtUsd = (v) => (v == null || Number.isNaN(Number(v))) ? '$—' : `${Number(v) >= 0 ? '+$' : '−$'}${Math.abs(Number(v)).toFixed(0)}`;
const fmtPct = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : `${(Number(v) * 100).toFixed(0)}%`;
const fmtPrice = (v) => (v == null || Number.isNaN(Number(v))) ? '—' : `$${Number(v).toFixed(2)}`;
const fmtChangePct = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
};
const fmtSwing = (v) => {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}`;
};

const Section = ({ title, accent = 'text-zinc-200', right, children, testid }) => (
  <section data-testid={testid} className="border-t border-zinc-800">
    <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-900 bg-zinc-950/40">
      <div className={`v5-mono text-[13px] font-bold tracking-widest uppercase ${accent}`}>{title}</div>
      {right}
    </div>
    <div className="px-4 py-3">{children}</div>
  </section>
);


const BriefingDeepDiveModal = memo(({ isOpen, onClose, briefingKey = 'morning' }) => {
  useV5Styles();
  const { loading, data, reload } = useMorningBriefing({ enabled: isOpen, refreshMs: 0 });
  const live = useBriefingLiveData({ enabled: isOpen });

  // Variant selection — defaults to morning if an unknown key is passed
  // so a typo in the parent doesn't render a blank header.
  const variant = BRIEFING_VARIANTS[briefingKey] || BRIEFING_VARIANTS.morning;
  const VariantIcon = variant.Icon;

  const gp = data?.game_plan;
  const drc = data?.drc;
  const scanner = data?.scanner;
  const bot = data?.bot;
  const positions = data?.positions || [];
  const summary = data?.summary;
  const safety = data?.safety;
  const drift = data?.drift || [];

  const { open, closed, totalUnrealizedPnl, totalRealizedPnl } = useMemo(() => {
    const open = positions.filter(p => (p.quantity || p.shares || 0) !== 0 && p.status !== 'closed');
    const closed = positions.filter(p => p.status === 'closed');
    return {
      open,
      closed,
      totalUnrealizedPnl: open.reduce((s, p) => s + (Number(p.unrealized_pnl) || 0), 0),
      totalRealizedPnl: closed.reduce((s, p) => s + (Number(p.realized_pnl) || Number(p.pnl) || 0), 0),
    };
  }, [positions]);

  if (!isOpen) return null;
  const quotesReady = summary?.quotes_ready !== false;

  const marketBias = gp?.market_bias || gp?.bias;
  const stocksInPlay = gp?.stocks_in_play || gp?.watchlist || [];
  const focusSetups = gp?.focus_setups || gp?.focus;
  const riskNotes = gp?.risk_notes || drc?.notes;
  const regime = gp?.regime || gp?.market_regime || scanner?.regime;
  const drcHealth = drc?.status || drc?.health;
  const maxRisk = drc?.max_daily_risk ?? drc?.max_daily_r;

  const dateLabel = new Date().toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  });
  const timeLabel = fmtET12(new Date());

  const biasChip = marketBias === 'bullish' || marketBias === 'LONG' ? 'v5-chip-manage'
                  : marketBias === 'bearish' || marketBias === 'SHORT' ? 'v5-chip-veto'
                  : 'v5-chip-close';

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.12 }}
        className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.98, opacity: 0, y: 12 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.98, opacity: 0, y: 12 }}
          transition={{ type: 'spring', damping: 28, stiffness: 320 }}
          className="w-full max-w-[min(108rem,95vw)] max-h-[88vh] overflow-hidden rounded-lg bg-zinc-950 border border-zinc-800 shadow-2xl v5-root"
          onClick={(e) => e.stopPropagation()}
          data-testid="morning-briefing-modal"
          data-help-id="briefings"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800 bg-zinc-950/90">
            <div className="flex items-center gap-3">
              <VariantIcon className={`w-5 h-5 ${variant.accent}`} />
              <span className={`v5-mono text-sm font-bold tracking-widest ${variant.accent}`}>
                {variant.label}
              </span>
              <span className="v5-mono text-xs v5-dim hidden md:inline">·</span>
              <span className="v5-mono text-xs v5-dim hidden md:inline">{variant.timeBand}</span>
              <span className="v5-mono text-xs v5-dim hidden lg:inline">·</span>
              <span className="v5-mono text-xs v5-dim hidden lg:inline">{dateLabel}</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => { reload(); live.reload(); }}
                className="p-2 rounded hover:bg-zinc-800 transition-colors"
                data-testid="briefing-refresh"
                title="Refresh"
              >
                <RefreshCw className={`w-4 h-4 text-zinc-400 ${loading || live.loading ? 'animate-spin' : ''}`} />
              </button>
              <button
                onClick={onClose}
                className="p-2 rounded hover:bg-zinc-800 transition-colors"
                data-testid="close-briefing"
              >
                <X className="w-4 h-4 text-zinc-400" />
              </button>
            </div>
          </div>

          {/* Variant blurb — sets context for the briefing variant */}
          <div className="px-5 py-2 border-b border-zinc-900 bg-zinc-950/40">
            <span className="text-xs text-zinc-400">{variant.blurb}</span>
          </div>

          {/* Top HUD — quick summary strip */}
          <div className="grid grid-cols-3 gap-px bg-zinc-900">
            <div className="bg-zinc-950 px-4 py-2">
              <div className="v5-mono text-[11px] uppercase tracking-widest text-zinc-500">Open P&L</div>
              <div className={`v5-mono text-lg font-bold ${quotesReady ? (totalUnrealizedPnl >= 0 ? 'v5-up' : 'v5-down') : 'v5-warn'}`}>
                {quotesReady ? fmtUsd(totalUnrealizedPnl) : 'pending'}
              </div>
              <div className="text-[11px] text-zinc-500">{open.length} position{open.length === 1 ? '' : 's'}</div>
            </div>
            <div className="bg-zinc-950 px-4 py-2">
              <div className="v5-mono text-[11px] uppercase tracking-widest text-zinc-500">Closed today</div>
              <div className={`v5-mono text-lg font-bold ${closed.length === 0 ? 'text-zinc-500' : (totalRealizedPnl >= 0 ? 'v5-up' : 'v5-down')}`}>
                {closed.length === 0 ? '—' : fmtUsd(totalRealizedPnl)}
              </div>
              <div className="text-[11px] text-zinc-500">{closed.length} fill{closed.length === 1 ? '' : 's'}</div>
            </div>
            <div className="bg-zinc-950 px-4 py-2">
              <div className="v5-mono text-[11px] uppercase tracking-widest text-zinc-500">DRC</div>
              <div className={`v5-mono text-lg font-bold ${
                !drcHealth ? 'text-zinc-500'
                : (drcHealth === 'green' || drcHealth === 'healthy') ? 'v5-up'
                : drcHealth === 'yellow' ? 'v5-warn'
                : 'v5-down'
              }`}>
                {drcHealth ? drcHealth.toUpperCase() : '—'}
              </div>
              <div className="text-[11px] text-zinc-500">{maxRisk != null ? `cap $${Math.round(maxRisk)}` : 'no cap set'}</div>
            </div>
          </div>

          <div className="max-h-[64vh] overflow-y-auto v5-scroll">
            {loading && !data && (
              <div className="flex items-center justify-center py-12">
                <RefreshCw className="w-4 h-4 text-violet-400 animate-spin" />
              </div>
            )}

            {/* P2-A: Top Movers on dynamic watchlist (positions + scanner top-10 + indices) */}
            <Section
              title="Top movers · watchlist"
              accent="text-emerald-400"
              testid="briefing-section-top-movers"
              right={
                live.marketState && (
                  <span data-testid="briefing-top-movers-market-state" className="v5-mono text-[11px] text-zinc-500 uppercase">
                    {live.marketState}
                  </span>
                )
              }
            >
              {live.loading && live.topMovers.length === 0 && (
                <div data-testid="briefing-top-movers-loading" className="v5-mono text-[12px] text-zinc-600">loading…</div>
              )}
              {!live.loading && live.topMovers.length === 0 && (
                <div data-testid="briefing-top-movers-empty" className="v5-mono text-[12px] text-zinc-600">
                  No live data (pusher offline or pre-trade)
                </div>
              )}
              {live.topMovers.length > 0 && (
                <div data-testid="briefing-top-movers-grid" className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-zinc-900">
                  {live.topMovers.map((s) => {
                    const up = (s.change_pct || 0) >= 0;
                    return (
                      <div
                        key={s.symbol}
                        data-testid={`briefing-mover-${s.symbol}`}
                        className="bg-zinc-950 px-3 py-2 flex flex-col gap-0.5"
                      >
                        <span className="v5-mono text-[12px] font-bold text-zinc-100">{s.symbol}</span>
                        <span className="v5-mono text-[12px] text-zinc-400">{fmtPrice(s.latest_price)}</span>
                        <span className={`v5-mono text-[12px] font-bold ${up ? 'v5-up text-emerald-400' : 'v5-down text-rose-400'}`}>
                          {fmtChangePct(s.change_pct)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </Section>

            {/* P2-A: Overnight sentiment swings (yesterday close vs premarket)
                Auto-hidden during RTH (09:30–16:00 ET) — the section is about
                pre-trade news prep, not intra-day reactions. Re-appears in
                extended / overnight / weekend market states. */}
            {live.marketState !== 'rth' && (
            <Section
              title="Overnight sentiment swings"
              accent="text-amber-400"
              testid="briefing-section-overnight-sentiment"
              right={
                <div className="flex items-center gap-1.5">
                  {live.yesterdayCloseHours != null && live.yesterdayCloseHours > 10 && (
                    <span
                      data-testid="briefing-weekend-catchup-badge"
                      className="v5-mono text-[11px] text-amber-400 uppercase tracking-wide"
                      title={`Window widened to catch weekend / holiday news since ${live.yesterdayCloseStart || 'last close'}`}
                    >
                      since {Math.round(live.yesterdayCloseHours)}h ago
                    </span>
                  )}
                  {live.notableSwingCount > 0 && (
                    <span data-testid="briefing-notable-swing-count" className="v5-chip v5-chip-veto">
                      {live.notableSwingCount} notable
                    </span>
                  )}
                </div>
              }
            >
              {live.loading && live.sentimentResults.length === 0 && (
                <div className="v5-mono text-[12px] text-zinc-600">loading…</div>
              )}
              {!live.loading && live.sentimentResults.length === 0 && (
                <div data-testid="briefing-sentiment-empty" className="v5-mono text-[12px] text-zinc-600">
                  No overnight news for watchlist symbols.
                </div>
              )}
              {live.sentimentResults.length > 0 && (
                <div data-testid="briefing-sentiment-list" className="space-y-1.5">
                  {live.sentimentResults.slice(0, 8).map((r) => {
                    const chipCls = r.swing_direction === 'up'
                      ? 'v5-chip v5-chip-manage'
                      : r.swing_direction === 'down'
                        ? 'v5-chip v5-chip-veto'
                        : 'v5-chip v5-chip-close';
                    return (
                      <div
                        key={r.symbol}
                        data-testid={`briefing-sentiment-${r.symbol}`}
                        className={`flex items-start gap-2 px-2 py-1.5 rounded ${r.notable ? 'bg-zinc-900/60' : ''}`}
                      >
                        <span className="v5-mono text-[12px] font-bold text-zinc-100 w-10 shrink-0">
                          {r.symbol}
                        </span>
                        <span className={`${chipCls} v5-mono text-[11px] shrink-0`} data-testid={`briefing-sentiment-chip-${r.symbol}`}>
                          {fmtSwing(r.swing)}
                        </span>
                        <span className="v5-mono text-[11px] text-zinc-500 shrink-0">
                          y.close {fmtSwing(r.sentiment_yesterday_close)} · pre {fmtSwing(r.sentiment_premarket)}
                        </span>
                        {r.top_headline && (
                          <span className="text-[12px] text-zinc-400 truncate flex-1" title={r.top_headline}>
                            · {r.top_headline}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </Section>
            )}

            {/* GAMEPLAN */}
            <Section
              title="Today's game plan"
              accent="text-violet-400"
              testid="briefing-section-gameplan"
              right={
                regime && (
                  <span className="v5-chip v5-chip-scan">{regime}</span>
                )
              }
            >
              {!gp ? (
                <div className="text-[13px] text-zinc-500 v5-why">
                  No game plan filed for today. Add one in your journal to see
                  regime, bias, stocks-in-play and focus setups here tomorrow.
                </div>
              ) : (
                <div className="space-y-2 text-[13px]">
                  {marketBias && (
                    <div className="flex items-center gap-2">
                      <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider">Bias</span>
                      <span className={`v5-chip ${biasChip}`}>{marketBias}</span>
                    </div>
                  )}
                  {stocksInPlay.length > 0 && (
                    <div>
                      <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider mb-2">
                        Stocks in play ({stocksInPlay.length})
                      </div>
                      {/* v19.20 — expandable per-stock cards with bullets,
                          level grid, and AI narrative (Ollama gpt-oss 120B).
                          Falls back to a compact chip row if the entries are
                          bare strings (legacy shape). */}
                      <div
                        className="space-y-1.5"
                        data-testid="briefing-stocks-in-play-list"
                      >
                        {stocksInPlay.slice(0, 12).map((s, i) => {
                          const sym = typeof s === 'string' ? s : (s.symbol || s.ticker);
                          if (!sym) return null;
                          // Legacy string entry — render a compact clickable chip
                          // so the upgrade path is lossless for older gameplans.
                          if (typeof s === 'string') {
                            return (
                              <span
                                key={i}
                                className="v5-chip v5-chip-eval inline-block mr-1"
                              >
                                {sym}
                              </span>
                            );
                          }
                          return (
                            <GamePlanStockCard
                              key={`${sym}-${i}`}
                              stock={s}
                              date={gp?.date}
                              marketBias={marketBias}
                            />
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {focusSetups && (
                    <div className="v5-why">
                      <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider">Focus: </span>
                      <span className="text-zinc-300">{focusSetups}</span>
                    </div>
                  )}
                  {riskNotes && (
                    <div className="v5-why">
                      <span className="v5-mono text-[12px] text-rose-400 uppercase tracking-wider">Risk: </span>
                      <span className="text-zinc-300">{riskNotes}</span>
                    </div>
                  )}
                  {gp.thesis && (
                    <div className="v5-why">
                      <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider">Thesis: </span>
                      <span className="text-zinc-300">{gp.thesis}</span>
                    </div>
                  )}
                </div>
              )}
            </Section>

            {/* OPEN POSITIONS */}
            {open.length > 0 && (
              <Section
                title={`Carry-over positions (${open.length})`}
                accent="text-emerald-400"
                testid="briefing-section-open"
                right={
                  <span className={`v5-mono text-xs font-bold ${quotesReady ? (totalUnrealizedPnl >= 0 ? 'v5-up' : 'v5-down') : 'v5-warn'}`}>
                    {quotesReady ? fmtUsd(totalUnrealizedPnl) : 'awaiting quotes'}
                  </span>
                }
              >
                <div className="space-y-1">
                  {open.slice(0, 8).map((p, i) => {
                    const dir = (p.direction || p.side || '').toLowerCase();
                    const chip = dir === 'short' ? 'v5-chip-veto' : 'v5-chip-manage';
                    const pnl = Number(p.unrealized_pnl) || 0;
                    return (
                      <div key={p.id || p._id || i} className="flex items-center justify-between gap-3 py-1 border-b border-zinc-900 last:border-b-0">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="v5-mono text-xs font-bold text-zinc-100">{p.symbol}</span>
                          <span className={`v5-chip ${chip}`}>{dir === 'short' ? 'SHORT' : 'LONG'}</span>
                          <span className="v5-mono text-[12px] v5-dim">{p.quantity || p.shares}sh</span>
                        </div>
                        {p.quote_ready === false ? (
                          <span className="v5-mono text-[12px] v5-warn">awaiting…</span>
                        ) : (
                          <span className={`v5-mono text-[13px] font-bold ${pnl >= 0 ? 'v5-up' : 'v5-down'}`}>
                            {fmtUsd(pnl)}
                          </span>
                        )}
                      </div>
                    );
                  })}
                  {open.length > 8 && (
                    <div className="text-[12px] v5-dim pt-1">+ {open.length - 8} more…</div>
                  )}
                </div>
              </Section>
            )}

            {/* SAFETY & TELEMETRY (2026-04-23) */}
            {safety && (
              <Section
                title="Safety & telemetry"
                accent="text-amber-400"
                testid="briefing-section-safety"
                right={
                  safety?.state?.kill_switch_tripped ? (
                    <span className="v5-chip v5-chip-veto">KILL-SWITCH</span>
                  ) : safety?.live?.awaiting_quotes ? (
                    <span className="v5-chip v5-chip-order">AWAITING QUOTES</span>
                  ) : (
                    <span className="v5-chip v5-chip-manage">OK</span>
                  )
                }
              >
                <div className="grid grid-cols-2 gap-px bg-zinc-900 -mx-4 -my-3">
                  <div className="bg-zinc-950 px-3 py-2">
                    <div className="v5-mono text-[11px] uppercase tracking-widest text-zinc-500">Kill switch</div>
                    <div className={`v5-mono text-xs font-bold ${safety?.state?.kill_switch_tripped ? 'v5-down' : 'v5-up'}`}>
                      {safety?.state?.kill_switch_tripped ? 'TRIPPED' : 'ARMED'}
                    </div>
                    {safety?.state?.kill_switch_reason && (
                      <div className="text-[11px] text-zinc-400 truncate">{safety.state.kill_switch_reason}</div>
                    )}
                  </div>
                  <div className="bg-zinc-950 px-3 py-2">
                    <div className="v5-mono text-[11px] uppercase tracking-widest text-zinc-500">Open positions</div>
                    <div className="v5-mono text-xs font-bold text-zinc-200">
                      {safety?.live?.open_positions_count ?? 0}
                    </div>
                    {safety?.live?.awaiting_quotes && (
                      <div className="text-[11px] text-amber-400 truncate" data-testid="briefing-awaiting-quotes">
                        awaiting: {(safety.live.positions_missing_quotes || []).slice(0, 3).join(', ') || '—'}
                      </div>
                    )}
                  </div>
                  <div className="bg-zinc-950 px-3 py-2">
                    <div className="v5-mono text-[11px] uppercase tracking-widest text-zinc-500">Daily loss cap</div>
                    <div className="v5-mono text-xs font-bold text-zinc-200">
                      ${Math.round(safety?.config?.max_daily_loss_usd ?? 0)}
                    </div>
                  </div>
                  <div className="bg-zinc-950 px-3 py-2">
                    <div className="v5-mono text-[11px] uppercase tracking-widest text-zinc-500">Max positions</div>
                    <div className="v5-mono text-xs font-bold text-zinc-200">
                      {safety?.config?.max_positions ?? '—'}
                    </div>
                  </div>
                </div>
              </Section>
            )}

            {/* MODEL HEALTH — per-model drift + calibration (2026-04-23) */}
            {drift && drift.length > 0 && (
              <Section
                title={`Model health (${drift.length})`}
                accent="text-fuchsia-400"
                testid="briefing-section-model-health"
                right={
                  <span
                    className={`v5-chip ${
                      drift.some((d) => d.status === 'critical')
                        ? 'v5-chip-veto'
                        : drift.some((d) => d.status === 'warning')
                        ? 'v5-chip-order'
                        : 'v5-chip-manage'
                    }`}
                  >
                    {
                      (drift.some((d) => d.status === 'critical') && 'DRIFT CRIT') ||
                      (drift.some((d) => d.status === 'warning') && 'DRIFT WARN') ||
                      'STABLE'
                    }
                  </span>
                }
              >
                <div className="space-y-1">
                  {drift.slice(0, 6).map((d) => {
                    const statusChip =
                      d.status === 'critical' ? 'v5-chip-veto'
                      : d.status === 'warning' ? 'v5-chip-order'
                      : d.status === 'insufficient_data' ? 'v5-chip-eval'
                      : 'v5-chip-manage';
                    return (
                      <div
                        key={d.model_version}
                        className="flex items-center justify-between gap-3 py-1 border-b border-zinc-900 last:border-b-0"
                        data-testid={`briefing-drift-row-${d.model_version}`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="v5-mono text-[13px] text-zinc-100 truncate">{d.model_version}</span>
                          <span className={`v5-chip ${statusChip}`}>{(d.status || '').toUpperCase()}</span>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          <span className="v5-mono text-[12px] v5-dim">PSI {d.psi != null ? d.psi.toFixed(2) : '—'}</span>
                          <span className="v5-mono text-[12px] v5-dim">KS {d.ks != null ? d.ks.toFixed(2) : '—'}</span>
                          <span className={`v5-mono text-[12px] ${d.mean_shift >= 0 ? 'v5-up' : 'v5-down'}`}>
                            Δμ {d.mean_shift != null ? (d.mean_shift >= 0 ? '+' : '') + d.mean_shift.toFixed(2) : '—'}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                  {drift.length > 6 && (
                    <div className="text-[12px] v5-dim pt-1">+ {drift.length - 6} more…</div>
                  )}
                </div>
              </Section>
            )}

            {/* SYSTEM */}
            <Section
              title="System status"
              accent="text-cyan-400"
              testid="briefing-section-system"
            >
              <div className="grid grid-cols-3 gap-px bg-zinc-900 -mx-4 -my-3">
                <div className="bg-zinc-950 px-3 py-2">
                  <div className={`v5-mono text-xs font-bold ${scanner?.mode || scanner?.running ? 'v5-up' : 'text-zinc-500'}`}>
                    {scanner?.mode || (scanner?.running ? 'ACTIVE' : 'IDLE')}
                  </div>
                  <div className="text-[11px] text-zinc-500 uppercase tracking-wider">Scanner</div>
                  {scanner?.total_hits != null && (
                    <div className="text-[12px] text-zinc-400 v5-mono">{scanner.total_hits} hits</div>
                  )}
                </div>
                <div className="bg-zinc-950 px-3 py-2">
                  <div className={`v5-mono text-xs font-bold ${bot?.is_active || bot?.running ? 'v5-up' : 'text-zinc-500'}`}>
                    {bot?.is_active || bot?.running ? 'ACTIVE' : 'IDLE'}
                  </div>
                  <div className="text-[11px] text-zinc-500 uppercase tracking-wider">Trading bot</div>
                  {bot?.mode && <div className="text-[12px] text-zinc-400 v5-mono">{bot.mode}</div>}
                </div>
                <div className="bg-zinc-950 px-3 py-2">
                  <div className="v5-mono text-xs font-bold v5-warn">PAPER</div>
                  <div className="text-[11px] text-zinc-500 uppercase tracking-wider">Account mode</div>
                  <div className="text-[12px] text-zinc-400 v5-mono">{timeLabel}</div>
                </div>
              </div>
            </Section>

            {/* DRC details */}
            {(drc && (drc.notes || drcHealth)) && (
              <Section
                title="Daily risk check"
                accent="text-rose-400"
                testid="briefing-section-drc"
              >
                <div className="space-y-1 text-[13px]">
                  {drcHealth && (
                    <div className="flex items-center gap-2">
                      <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider">Status</span>
                      <span className={`v5-chip ${drcHealth === 'green' || drcHealth === 'healthy' ? 'v5-chip-manage' : drcHealth === 'yellow' ? 'v5-chip-order' : 'v5-chip-veto'}`}>
                        {drcHealth.toUpperCase()}
                      </span>
                    </div>
                  )}
                  {maxRisk != null && (
                    <div className="v5-why">
                      <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider">Daily risk cap: </span>
                      <span className="v5-mono text-zinc-200">${Math.round(maxRisk)}</span>
                    </div>
                  )}
                  {drc.used != null && (
                    <div className="v5-why">
                      <span className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wider">Used: </span>
                      <span className={`v5-mono ${drc.used >= maxRisk ? 'v5-down' : 'text-zinc-200'}`}>
                        ${Math.round(drc.used)} ({fmtPct(drc.used / Math.max(1e-6, maxRisk))})
                      </span>
                    </div>
                  )}
                  {drc.notes && <div className="v5-why text-zinc-400">{drc.notes}</div>}
                </div>
              </Section>
            )}
          </div>

          {/* Footer — single CTA */}
          <div className="px-4 py-3 border-t border-zinc-800 bg-zinc-950/90 flex items-center justify-between">
            <span className="v5-mono text-[11px] v5-dim">
              Auto-popup disabled · opens only via the briefing button
            </span>
            <button
              onClick={onClose}
              className="px-4 py-1.5 rounded-sm bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/40 text-violet-200 v5-mono text-[13px] font-bold uppercase tracking-widest transition-colors"
              data-testid="start-trading-btn"
            >
              Let's trade →
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
});

BriefingDeepDiveModal.displayName = 'BriefingDeepDiveModal';

// Backwards-compat alias — existing call sites that import the old
// name keep working without a code change. New call sites should
// prefer `BriefingDeepDiveModal` and pass a `briefingKey` prop.
const MorningBriefingModal = BriefingDeepDiveModal;

export { BriefingDeepDiveModal };
export default MorningBriefingModal;
