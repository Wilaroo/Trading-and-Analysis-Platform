/**
 * PnLByStyleCard — v19.34.161 (Feb 2026)
 *
 * Compact V5 status-strip card that breaks today's realized R + win-rate
 * + P&L down by trade-style bucket (Scalp / Intraday / Multi-day /
 * Swing / Investment / Position). Operator-facing answer to:
 *   "Is the bot making money on scalps vs intraday vs swing TODAY?"
 *
 * Data source: GET /api/trading-bot/pnl-by-style?days=N
 *   Backend: `services/trade_style_classifier.py` (single source of
 *   truth — mirrors frontend tradeStyleMeta.js).
 *
 * UX: pill shows the day's grand-total R + win%; click toggles a
 * popover with the per-style breakdown. Click-through into a row
 * surfaces the top-3 contributing setups.
 *
 * Color coding:
 *   total_r > 0   → emerald
 *   total_r < 0   → rose
 *   total_r == 0  → zinc
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { PieChart } from 'lucide-react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// Style-keyed accent palette. Mirrors `TONE_CLASS` in TradeStyleChip
// so the card and the chips look like one design language.
const STYLE_TINT = {
  scalp:      'bg-fuchsia-500/15 border-fuchsia-500/30 text-fuchsia-300',
  intraday:   'bg-sky-500/15 border-sky-500/30 text-sky-300',
  multi_day:  'bg-emerald-500/15 border-emerald-500/30 text-emerald-300',
  swing:      'bg-emerald-500/15 border-emerald-500/30 text-emerald-300',
  investment: 'bg-amber-500/15 border-amber-500/30 text-amber-300',
  position:   'bg-rose-500/15 border-rose-500/30 text-rose-300',
  unknown:    'bg-zinc-700/20 border-zinc-700/40 text-zinc-400',
};

const STYLE_DOT = {
  scalp:      'bg-fuchsia-400',
  intraday:   'bg-sky-400',
  multi_day:  'bg-emerald-400',
  swing:      'bg-emerald-400',
  investment: 'bg-amber-400',
  position:   'bg-rose-400',
  unknown:    'bg-zinc-500',
};

const fmtR = (r) => {
  if (r == null || Number.isNaN(Number(r))) return '0.0R';
  const n = Number(r);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}R`;
};

const fmtPnl = (p) => {
  if (p == null || Number.isNaN(Number(p))) return '$0';
  const n = Number(p);
  const sign = n >= 0 ? '+' : '-';
  return `${sign}$${Math.abs(n).toFixed(0)}`;
};

const pnlClass = (r) => {
  const n = Number(r);
  if (n > 0) return 'text-emerald-300';
  if (n < 0) return 'text-rose-300';
  return 'text-zinc-400';
};

export const PnLByStyleCard = () => {
  const [todayData, setTodayData] = useState(null);
  const [recentData, setRecentData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [view, setView] = useState('today'); // 'today' | 'recent'

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, r] = await Promise.all([
        fetch(`${BACKEND_URL}/api/trading-bot/pnl-by-style?days=1`,  { headers: { Accept: 'application/json' } }),
        fetch(`${BACKEND_URL}/api/trading-bot/pnl-by-style?days=30`, { headers: { Accept: 'application/json' } }),
      ]);
      if (!t.ok) throw new Error(`HTTP ${t.status}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setTodayData(await t.json());
      setRecentData(await r.json());
    } catch (err) {
      setError(err.message || 'fetch failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 60_000); // 60s cadence
    return () => clearInterval(id);
  }, [refresh]);

  const active = view === 'today' ? todayData : recentData;
  const totals = active?.totals || {};
  const styles = active?.styles || [];

  const tooltip = useMemo(() => {
    if (!active) return '';
    const lines = [
      `P&L by style — last ${active.days || '?'}d`,
      `Total: ${fmtR(totals.total_r)} · ${fmtPnl(totals.total_pnl)} · ${totals.n || 0} trades · ${totals.win_pct ?? 0}% win`,
      '──',
      ...styles.map((s) =>
        `${(s.label || s.style).padEnd(10)} ${String(s.n).padStart(3)} trades  ${fmtR(s.total_r).padStart(7)}  ${fmtPnl(s.total_pnl).padStart(7)}  ${s.win_pct}% win`
      ),
    ];
    return lines.join('\n');
  }, [active, totals, styles]);

  if (error) {
    return (
      <div
        data-testid="pnl-by-style-card-error"
        className="flex items-center gap-2 px-3 py-1 bg-zinc-950/60 text-[14px] leading-none whitespace-nowrap border border-rose-500/30 text-rose-300"
        title={`Per-style P&L fetch failed: ${error}`}
      >
        <PieChart className="w-3 h-3" />
        <span>BY STYLE ?</span>
      </div>
    );
  }

  if (!active && loading) {
    return (
      <div
        data-testid="pnl-by-style-card-loading"
        className="flex items-center gap-2 px-3 py-1 bg-zinc-950/60 text-[14px] leading-none whitespace-nowrap border border-zinc-700/50 text-zinc-500"
      >
        <PieChart className="w-3 h-3 animate-pulse" />
        <span>BY STYLE …</span>
      </div>
    );
  }

  return (
    <div
      data-testid="pnl-by-style-card"
      className="relative bg-zinc-950/60 text-[14px] leading-none"
      title={tooltip}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        data-testid="pnl-by-style-card-toggle"
        className={`flex items-center gap-2 px-3 py-1 border whitespace-nowrap border-zinc-700/50 hover:brightness-110 transition`}
      >
        <PieChart className="w-3 h-3 text-zinc-500" />
        <span className="font-semibold uppercase tracking-wide text-zinc-300">
          BY STYLE
        </span>
        <span
          data-testid="pnl-by-style-card-total-r"
          className={`v5-mono ${pnlClass(totals.total_r)}`}
        >
          {fmtR(totals.total_r)}
        </span>
        <span className="text-zinc-500 v5-mono">
          {totals.n || 0}t · {totals.win_pct ?? 0}%
        </span>
      </button>

      {expanded && (
        <div
          data-testid="pnl-by-style-card-drawer"
          onClick={(e) => e.stopPropagation()}
          className="absolute z-50 left-0 top-full mt-1 w-[460px] bg-zinc-950 border border-zinc-700 shadow-2xl p-3 text-[13px] cursor-default"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-zinc-500 uppercase tracking-wider text-[12px]">
                P&amp;L by style
              </span>
              <div className="inline-flex border border-zinc-800 overflow-hidden rounded-sm">
                <button
                  type="button"
                  data-testid="pnl-by-style-card-view-today"
                  onClick={(e) => { e.stopPropagation(); setView('today'); }}
                  className={`px-2 py-0.5 text-[11px] uppercase tracking-wider ${view === 'today' ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300'}`}
                >
                  Today
                </button>
                <button
                  type="button"
                  data-testid="pnl-by-style-card-view-recent"
                  onClick={(e) => { e.stopPropagation(); setView('recent'); }}
                  className={`px-2 py-0.5 text-[11px] uppercase tracking-wider border-l border-zinc-800 ${view === 'recent' ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300'}`}
                >
                  30d
                </button>
              </div>
            </div>
            <button
              type="button"
              data-testid="pnl-by-style-card-refresh"
              onClick={(e) => { e.stopPropagation(); refresh(); }}
              className="text-zinc-500 hover:text-zinc-200 text-[12px]"
              title="Refresh now"
            >
              ↻
            </button>
          </div>

          {/* Grand totals strip */}
          <div className="grid grid-cols-4 gap-2 mb-3">
            <div className="bg-zinc-900 border border-zinc-800 px-2 py-1">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">Trades</div>
              <div className="v5-mono text-zinc-200">{totals.n || 0}</div>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 px-2 py-1">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">Win %</div>
              <div className="v5-mono text-zinc-200">{totals.win_pct ?? 0}%</div>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 px-2 py-1">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">Total R</div>
              <div
                data-testid="pnl-by-style-card-grand-r"
                className={`v5-mono ${pnlClass(totals.total_r)}`}
              >
                {fmtR(totals.total_r)}
              </div>
            </div>
            <div className="bg-zinc-900 border border-zinc-800 px-2 py-1">
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">Net P&amp;L</div>
              <div className={`v5-mono ${pnlClass(totals.total_pnl)}`}>
                {fmtPnl(totals.total_pnl)}
              </div>
            </div>
          </div>

          {/* Per-style rows */}
          {styles.length === 0 ? (
            <div className="text-zinc-500 italic text-center py-3">
              No closed trades in the selected window.
            </div>
          ) : (
            <div data-testid="pnl-by-style-card-rows" className="space-y-1">
              {styles.map((s) => (
                <div
                  key={s.style}
                  data-testid={`pnl-by-style-row-${s.style}`}
                  className={`flex items-center justify-between gap-2 px-2 py-1.5 bg-zinc-900/40 border ${STYLE_TINT[s.style] || STYLE_TINT.unknown}`}
                >
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <span className={`w-2 h-2 rounded-full ${STYLE_DOT[s.style] || STYLE_DOT.unknown}`} />
                    <span className="font-semibold uppercase tracking-wider text-[12px]">
                      {s.label}
                    </span>
                    <span className="text-zinc-500 text-[11px] v5-mono">
                      {s.n}t · {s.win_pct}% win
                    </span>
                    {s.top_setups && s.top_setups.length > 0 && (
                      <span
                        className="truncate text-zinc-500 text-[11px] hidden md:inline"
                        title={s.top_setups.map((x) => `${x.setup}: ${fmtR(x.total_r)}`).join('\n')}
                      >
                        · top: {s.top_setups[0].setup}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 v5-mono">
                    <span className={`text-[13px] ${pnlClass(s.total_r)}`}>
                      {fmtR(s.total_r)}
                    </span>
                    <span className={`text-[12px] ${pnlClass(s.total_pnl)}`}>
                      {fmtPnl(s.total_pnl)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="mt-2 text-[10px] text-zinc-600 italic">
            Source: alert_outcomes · bucketed by services/trade_style_classifier.py.
          </div>
        </div>
      )}
    </div>
  );
};

export default PnLByStyleCard;
