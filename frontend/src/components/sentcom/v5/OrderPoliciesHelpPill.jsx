/**
 * OrderPoliciesHelpPill — v19.34.101 (Feb 2026)
 *
 * Operator-facing "rulebook" pill in the V5 HUD top strip.
 *
 * Calls GET /api/trading-bot/order-policies (single source of truth lives
 * in services/order_policy_registry.py) and renders the full per-style
 * execution policy on hover so the operator can confirm, at-a-glance:
 *   • Which TIF each horizon uses (DAY vs GTC)
 *   • Whether outside-RTH fills are allowed
 *   • The TP scale-out ladder (rungs + R-multiples)
 *   • Which indicator the trailing stop anchors on
 *   • Whether the trade is exempt from the EOD sweep
 *
 * Pattern intentionally mirrors LLMRulesPill so the HUD stays visually
 * cohesive. Pure read-only (no state, no writes) — safe to mount even
 * when the bot is idle.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// Display order = increasing time horizon, matches the operator's mental model.
const STYLE_ORDER = ['scalp', 'intraday', 'multi_day', 'swing', 'investment', 'position'];

const STYLE_LABEL = {
  scalp: 'Scalp',
  intraday: 'Intraday',
  multi_day: 'Multi-day',
  swing: 'Swing',
  investment: 'Investment',
  position: 'Position',
};

// Friendly indicator names for the trail-anchor field.
const ANCHOR_LABEL = {
  atr: 'ATR',
  ema_9: '9-EMA',
  ema_20: '20-EMA',
  sma_50: '50-SMA',
  sma_150: '30-week SMA',
  sma_200: '200-SMA',
  structure: 'Swing structure',
  fixed: 'Fixed (no trail)',
};

const fmtLadder = (rungs) => {
  if (!Array.isArray(rungs) || rungs.length === 0) return '—';
  return rungs
    .map((r) => `${Math.round((r.pct_of_position ?? 0) * 100)}% @ ${r.r_multiple}R`)
    .join(' · ');
};

export default function OrderPoliciesHelpPill() {
  const [policies, setPolicies] = useState(null);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);
  const fetchedRef = useRef(false);

  const fetchPolicies = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/api/trading-bot/order-policies`);
      if (!r.ok) {
        setError(true);
        return;
      }
      const j = await r.json();
      if (j && j.success && j.policies) {
        setPolicies(j.policies);
        setError(false);
      }
    } catch (_) {
      setError(true);
    }
  }, []);

  // Lazy-load: only fetch when operator first opens the pill. Policies
  // are effectively static (file-defined), so a one-shot fetch is fine.
  useEffect(() => {
    if (open && !fetchedRef.current) {
      fetchedRef.current = true;
      fetchPolicies();
    }
  }, [open, fetchPolicies]);

  return (
    <div
      className="relative inline-flex items-center"
      data-testid="order-policies-pill"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        data-testid="order-policies-pill-button"
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[12px] font-medium bg-violet-500/15 text-violet-300 border-violet-500/40 hover:bg-violet-500/25 transition-colors"
        title="Per-style execution policy (TIF, scale-outs, trail anchors)"
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden>▤</span>
        <span>policies</span>
      </button>

      {open && (
        <div
          className="absolute z-50 top-full mt-1 right-0 w-[520px] max-h-[70vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900/95 backdrop-blur-md shadow-xl p-3 text-[12px] text-zinc-200"
          data-testid="order-policies-tooltip"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="text-[11px] uppercase tracking-wider text-zinc-400">
              Order policy registry · live
            </div>
            <div className="text-[10px] text-zinc-500 v5-mono">
              v19.34.100
            </div>
          </div>

          {error && !policies && (
            <div
              className="text-rose-300 text-[11px] py-2"
              data-testid="order-policies-error"
            >
              Couldn't fetch /api/trading-bot/order-policies. Backend reachable?
            </div>
          )}

          {!policies && !error && (
            <div className="text-zinc-500 text-[11px] py-2">Loading policies…</div>
          )}

          {policies && (
            <div className="space-y-2.5">
              {STYLE_ORDER.filter((k) => policies[k]).map((key) => {
                const p = policies[key];
                const isGtc = p.time_in_force === 'GTC';
                const isProtected = p.eod_sweep_eligible === false;
                return (
                  <div
                    key={key}
                    data-testid={`order-policy-row-${key}`}
                    className="rounded-md border border-zinc-800 bg-zinc-950/60 p-2"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-zinc-100">
                          {STYLE_LABEL[key] || key}
                        </span>
                        <span className="text-[10px] text-zinc-500 v5-mono">
                          {p.horizon_label}
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span
                          className={`px-1.5 py-[1px] rounded text-[10px] font-semibold border ${
                            isGtc
                              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                              : 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                          }`}
                          data-testid={`order-policy-tif-${key}`}
                        >
                          {p.time_in_force}
                        </span>
                        {p.outside_rth && (
                          <span className="px-1.5 py-[1px] rounded text-[10px] font-semibold border border-cyan-500/40 bg-cyan-500/10 text-cyan-300">
                            Outside-RTH
                          </span>
                        )}
                        {isProtected && (
                          <span
                            className="px-1.5 py-[1px] rounded text-[10px] font-semibold border border-violet-500/40 bg-violet-500/10 text-violet-300"
                            title="Exempt from the EOD orphan sweep"
                          >
                            EOD-safe
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-[110px_1fr] gap-x-2 gap-y-0.5 tabular-nums text-[11px]">
                      <div className="text-zinc-500">TP ladder</div>
                      <div
                        className="text-zinc-200 v5-mono"
                        data-testid={`order-policy-ladder-${key}`}
                      >
                        {fmtLadder(p.tp_ladder)}
                      </div>

                      <div className="text-zinc-500">Trail anchor</div>
                      <div className="text-zinc-200">
                        {ANCHOR_LABEL[p.stop_trail_anchor] || p.stop_trail_anchor}
                        {p.stop_trail_anchor === 'atr' && p.stop_atr_multiple != null && (
                          <span className="text-zinc-500"> · {p.stop_atr_multiple}× ATR</span>
                        )}
                        {p.stop_trail_anchor !== 'atr' && p.stop_atr_multiple != null && (
                          <span className="text-zinc-500"> · initial {p.stop_atr_multiple}× ATR</span>
                        )}
                      </div>

                      <div className="text-zinc-500">Break-even</div>
                      <div className="text-zinc-200">
                        {p.stop_breakeven_at_r != null
                          ? `at +${p.stop_breakeven_at_r}R`
                          : 'never'}
                      </div>

                      <div className="text-zinc-500">EOD behavior</div>
                      <div className="text-zinc-200">
                        {p.close_at_eod ? (
                          <span className="text-amber-300">Force-close at bell</span>
                        ) : (
                          <span className="text-emerald-300">Hold overnight</span>
                        )}
                        {' · '}
                        {p.eod_sweep_eligible ? (
                          <span className="text-zinc-400">sweep-eligible</span>
                        ) : (
                          <span className="text-violet-300">sweep-protected</span>
                        )}
                      </div>
                    </div>

                    {p.notes && (
                      <div className="mt-1 text-[11px] leading-snug text-zinc-400 italic">
                        {p.notes}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="border-t border-zinc-700 mt-2 pt-1.5 text-[10px] text-zinc-500 leading-snug">
            Source of truth: <span className="v5-mono text-zinc-400">services/order_policy_registry.py</span>.
            All executors, EOD-sweepers and the stop-manager read from this registry.
          </div>
        </div>
      )}
    </div>
  );
}
