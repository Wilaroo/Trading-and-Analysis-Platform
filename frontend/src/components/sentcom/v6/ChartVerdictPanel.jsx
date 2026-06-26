/**
 * ChartVerdictPanel — V6 §4 center column: live price chart (top) + a per-symbol
 * VERDICT strip (bottom) answering "would the bot trade this, and why/why-not".
 *
 * Chart = the real V5 `ChartPanel` (lightweight-charts, self-fetching) for the
 * selected symbol. Verdict = `/api/scanner/symbol-trace` (gate funnel) — plain-
 * language verdict + universe/tier/RVOL + today's alert/trade counts + the FIRST
 * killing gate (or recomputed intake reasons) so the operator sees the WHY.
 */
import React, { useState } from 'react';
import { Search } from 'lucide-react';
import { ChartPanel } from '../panels/ChartPanel';
import { useSymbolTrace } from '../hooks/useSymbolTrace';

const verdictTone = (verdict = '') => {
  const v = verdict.toLowerCase();
  if (/(traded|alerted|eligible|healthy|firing)/.test(v)) return { dot: 'bg-emerald-400', text: 'text-emerald-300' };
  if (/(error|not initialized|stale|blocked|killed)/.test(v)) return { dot: 'bg-rose-400', text: 'text-rose-300' };
  return { dot: 'bg-amber-400', text: 'text-amber-300' };
};

const Stat = ({ label, value }) => (
  <div className="flex flex-col min-w-0">
    <span className="text-[9px] uppercase tracking-wider text-zinc-600">{label}</span>
    <span className="text-xs font-mono text-zinc-300 truncate">{value}</span>
  </div>
);

const yesNo = (v) => (v === true ? 'yes' : v === false ? 'no' : '—');

const VerdictStrip = ({ symbol, trace }) => {
  if (!symbol) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-600 text-xs" data-testid="v6-verdict-empty">
        Select a symbol in the Scanner or Open Positions to see its verdict.
      </div>
    );
  }
  const t = trace || {};
  const tone = verdictTone(t.verdict);
  const counts = t.today_counts || t.counts || {};
  const gf = t.gate_funnel || {};
  const byGate = gf.by_gate || {};
  const topGates = Object.entries(byGate).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const intakeReasons = Object.entries((t.intake || {}).by_reason || {}).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const rvolObj = t.rvol || {};
  const rvol = rvolObj.value != null ? `${rvolObj.value}×${rvolObj.fresh === false ? ' (stale)' : ''}` : '—';

  return (
    <div className="h-full overflow-y-auto p-3 space-y-3" data-testid="v6-verdict-strip">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-zinc-100">{t.symbol || symbol}</span>
        <span className={`flex items-center gap-1.5 text-xs font-semibold ${tone.text}`}>
          <span className={`w-2 h-2 rounded-full ${tone.dot} animate-pulse`} />
          {t.verdict || 'evaluating…'}
        </span>
      </div>
      {t.message && <p className="text-[11px] text-zinc-500 leading-snug">{t.message}</p>}

      <div className="grid grid-cols-3 gap-x-3 gap-y-2">
        <Stat label="Universe" value={yesNo(t.in_universe)} />
        <Stat label="Tier" value={t.tier ?? '—'} />
        <Stat label="In last wave" value={yesNo(t.in_last_wave)} />
        <Stat label="RVOL" value={rvol} />
        <Stat label="Alerts today" value={counts.live_alerts ?? counts.alerts ?? 0} />
        <Stat label="Trades today" value={counts.bot_trades ?? 0} />
      </div>

      {gf.total > 0 ? (
        <div className="rounded border border-rose-500/20 bg-rose-500/5 p-2" data-testid="v6-verdict-gate-funnel">
          <div className="text-[10px] uppercase tracking-wider text-rose-300/80 mb-1">
            Blocked at: <span className="font-bold text-rose-300">{gf.first_killing_gate || '—'}</span>
            <span className="text-zinc-500"> · {gf.total} drop(s) today</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {topGates.map(([gate, n]) => (
              <span key={gate} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-zinc-300">
                {gate} ×{n}
              </span>
            ))}
          </div>
        </div>
      ) : intakeReasons.length > 0 ? (
        <div className="rounded border border-amber-500/20 bg-amber-500/5 p-2" data-testid="v6-verdict-intake">
          <div className="text-[10px] uppercase tracking-wider text-amber-300/80 mb-1">Won't auto-trade — recomputed reasons</div>
          <div className="flex flex-wrap gap-1.5">
            {intakeReasons.map(([reason, n]) => (
              <span key={reason} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-zinc-300">
                {reason} ×{n}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-[11px] text-zinc-600" data-testid="v6-verdict-clean">No gate drops recorded today.</div>
      )}
    </div>
  );
};

export const ChartVerdictPanel = ({ symbol, position = null, onSymbolChange = null, className = '' }) => {
  const sym = symbol || 'SPY';
  const { trace } = useSymbolTrace(symbol);
  const [query, setQuery] = useState('');

  const submitSymbol = (e) => {
    e.preventDefault();
    const next = query.trim().toUpperCase();
    if (next && onSymbolChange) {
      onSymbolChange(next);
      setQuery('');
    }
  };

  return (
    <div
      className={`rounded-md border border-white/10 bg-white/[0.02] flex flex-col h-full min-h-0 overflow-hidden ${className}`}
      data-testid="v6-chart-verdict-panel"
    >
      <div className="px-3 py-2 border-b border-white/5 flex items-center gap-3 shrink-0">
        <span className="text-[11px] uppercase tracking-widest text-zinc-500 shrink-0">Chart + Verdict</span>
        {onSymbolChange && (
          <form onSubmit={submitSymbol} className="flex items-center gap-1 ml-auto" data-testid="v6-symbol-search-form">
            <div className="relative">
              <Search className="w-3 h-3 text-zinc-600 absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                data-testid="v6-symbol-search-input"
                value={query}
                onChange={(e) => setQuery(e.target.value.toUpperCase())}
                placeholder="SYMBOL"
                spellCheck={false}
                className="w-32 bg-black/40 border border-white/10 rounded pl-7 pr-2 py-1 text-[11px] font-mono uppercase tracking-wide text-zinc-200 placeholder:text-zinc-600 placeholder:tracking-widest focus:outline-none focus:border-cyan-500/50 focus:bg-black/60 transition-colors"
              />
            </div>
            <button
              type="submit"
              data-testid="v6-symbol-search-submit"
              className="text-[10px] uppercase font-bold tracking-wider px-2 py-1 rounded bg-white/5 text-zinc-400 hover:bg-cyan-500/20 hover:text-cyan-200 transition-colors disabled:opacity-30 disabled:hover:bg-white/5 disabled:hover:text-zinc-400"
              disabled={!query.trim()}
            >
              go
            </button>
          </form>
        )}
        <span className="text-[11px] font-mono text-zinc-400 shrink-0">{sym}</span>
      </div>
      <div className="flex-1 min-h-0 flex flex-col">
        <div className="flex-1 min-h-0" data-testid="v6-chart-host">
          <ChartPanel symbol={sym} position={position} className="h-full" />
        </div>
        <div className="h-[150px] shrink-0 border-t border-white/5 bg-black/20">
          <VerdictStrip symbol={symbol} trace={trace} />
        </div>
      </div>
    </div>
  );
};

export default ChartVerdictPanel;
