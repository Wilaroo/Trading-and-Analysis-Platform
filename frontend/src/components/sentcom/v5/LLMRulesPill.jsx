/**
 * LLMRulesPill — v19.34.64 (Feb 2026).
 *
 * Tiny status pill in the V5 HUD top strip showing the live computed
 * values of the equity-tied rules the chat-AI enforces (per v19.34.63).
 *
 * Surface:
 *   "🛡 11/13 · risk $2.5K · DLP -0.4%"
 *   - 11/13 = open_positions_count / position_count_cap
 *   - $2.5K = current per-trade risk cap (max(1% × equity, $2,500))
 *   - -0.4% = today's realized P&L as % of equity (red if breached)
 *
 * Color rules:
 *   - emerald: positions < cap AND daily_loss not breached
 *   - amber:   at/over position cap (advisory, not blocking)
 *   - red:     daily-loss circuit-breaker breached (pnl_pct ≤ -1%)
 *
 * Hover tooltip: full rules text + live equity / DLP / R:R min.
 *
 * Polls /api/trading-bot/llm-rules every 30s.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const fmtMoney = (n) => {
  if (n == null || isNaN(n)) return '—';
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
};

const fmtPct = (n) => {
  if (n == null || isNaN(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
};

export default function LLMRulesPill() {
  const [data, setData] = useState(null);
  const [hover, setHover] = useState(false);
  const timer = useRef(null);

  const tick = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/api/trading-bot/llm-rules`);
      if (!r.ok) return;
      const j = await r.json();
      if (j && j.success) setData(j);
    } catch (_) {
      /* decorative pill — silent on transient errors */
    }
  }, []);

  useEffect(() => {
    tick();
    timer.current = setInterval(tick, 30000);
    return () => clearInterval(timer.current);
  }, [tick]);

  if (!data) return null;
  const live = data.live_state || {};
  const breached = !!live.daily_loss_breached;
  const atCap = !!live.at_or_over_position_cap;

  // Color tier: red (breached) > amber (at cap) > emerald (clean)
  const tier = breached ? 'red' : atCap ? 'amber' : 'emerald';
  const tierClass = {
    red: 'bg-red-500/20 text-red-300 border-red-500/40',
    amber: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
    emerald: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  }[tier];

  return (
    <div
      className="relative inline-flex items-center"
      data-testid="llm-rules-pill"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <span
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[12px] font-medium tabular-nums ${tierClass}`}
      >
        <span aria-hidden>🛡</span>
        <span data-testid="llm-rules-positions">
          {live.open_positions_count ?? 0}/{data.position_count_cap ?? 10}
        </span>
        <span className="opacity-60">·</span>
        <span data-testid="llm-rules-risk">
          risk {fmtMoney(data.risk_per_trade_cap)}
        </span>
        <span className="opacity-60">·</span>
        <span
          data-testid="llm-rules-dlp"
          className={breached ? 'font-semibold' : ''}
        >
          DLP {fmtPct(live.today_realized_pnl_pct)}
        </span>
      </span>

      {hover && (
        <div
          className="absolute z-50 top-full mt-1 right-0 w-[360px] rounded-lg border border-zinc-700 bg-zinc-900/95 backdrop-blur-md shadow-xl p-3 text-[12px] text-zinc-200"
          data-testid="llm-rules-tooltip"
        >
          <div className="text-[11px] uppercase tracking-wider text-zinc-400 mb-1.5">
            Chat-AI rules · live
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 mb-2 tabular-nums">
            <div className="text-zinc-400">Equity</div>
            <div className="text-right">${(data.equity || 0).toLocaleString()}</div>
            <div className="text-zinc-400">Risk/trade cap</div>
            <div className="text-right">{fmtMoney(data.risk_per_trade_cap)}</div>
            <div className="text-zinc-400">Position cap</div>
            <div className="text-right">
              {live.open_positions_count}/{data.position_count_cap}
              {atCap && (
                <span className="ml-1 text-amber-400">(at cap)</span>
              )}
            </div>
            <div className="text-zinc-400">Daily loss budget</div>
            <div className="text-right">
              {fmtMoney(data.daily_loss_budget)}
            </div>
            <div className="text-zinc-400">Today realized P&L</div>
            <div
              className={`text-right ${
                breached ? 'text-red-400' : (live.today_realized_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-zinc-300'
              }`}
            >
              ${(live.today_realized_pnl ?? 0).toLocaleString()} ·{' '}
              {fmtPct(live.today_realized_pnl_pct)}
              {breached && (
                <span className="ml-1 font-semibold">⚠ breached</span>
              )}
            </div>
            <div className="text-zinc-400">Min R:R</div>
            <div className="text-right">{data.rr_min ?? '—'}:1</div>
            <div className="text-zinc-400">Concentration cap</div>
            <div className="text-right">
              {data.position_concentration_cap_pct ?? '—'}%
            </div>
          </div>
          <div className="border-t border-zinc-700 pt-1.5">
            <div className="text-[11px] uppercase tracking-wider text-zinc-400 mb-1">
              Active rules
            </div>
            <ul className="space-y-0.5 text-[11px] leading-snug text-zinc-300">
              {(data.rules_text || []).map((r, i) => (
                <li key={i} className="flex">
                  <span className="text-zinc-500 mr-1.5 flex-shrink-0">·</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
