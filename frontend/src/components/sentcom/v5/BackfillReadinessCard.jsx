/**
 * BackfillReadinessCard — the "OK to train?" card shown at the top of
 * the FreshnessInspector modal.
 *
 * Calls `GET /api/backfill/readiness` once on mount and on manual
 * refresh (via `refreshToken` prop). Each per-check tile is now
 * click-to-expand: opens an inline drawer with the actual numbers
 * (fresh_pct, per_timeframe breakdown, queue counters, low-density
 * sample, etc.) plus a suggested action — usually a one-click button
 * that POSTs to the right `/api/ib-collector/*` endpoint.
 *
 * Read-only on the train side — no Train All button here on purpose.
 */

import React, { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

const VERDICT_STYLE = {
  green: {
    pill: 'bg-emerald-900/40 text-emerald-200 border-emerald-700',
    dot: 'bg-emerald-400 animate-pulse',
    label: 'READY',
  },
  yellow: {
    pill: 'bg-amber-900/40 text-amber-200 border-amber-700',
    dot: 'bg-amber-400',
    label: 'NOT READY',
  },
  red: {
    pill: 'bg-rose-900/40 text-rose-200 border-rose-700',
    dot: 'bg-rose-400 animate-pulse',
    label: 'NOT READY',
  },
  unknown: {
    pill: 'bg-zinc-900/40 text-zinc-400 border-zinc-800',
    dot: 'bg-zinc-500',
    label: '—',
  },
};

const CHECK_LABELS = {
  queue_drained: 'Queue drained',
  critical_symbols_fresh: 'Critical symbols fresh',
  overall_freshness: 'Overall freshness',
  no_duplicates: 'No duplicate bars',
  density_adequate: 'Density adequate',
};

// ---------------------------------------------------------------------------
// Per-check expanded drawers — each gets its own renderer so the visualization
// matches the shape of the data the backend actually returns. Drawers degrade
// gracefully when fields are missing (e.g. the check timed out).
// ---------------------------------------------------------------------------

const NumPill = ({ label, value, tone = 'zinc', testid }) => {
  const TONES = {
    zinc:    'bg-zinc-800/60 text-zinc-200 border-zinc-700',
    emerald: 'bg-emerald-900/30 text-emerald-200 border-emerald-800',
    amber:   'bg-amber-900/30 text-amber-200 border-amber-800',
    rose:    'bg-rose-900/30 text-rose-200 border-rose-800',
    cyan:    'bg-cyan-900/30 text-cyan-200 border-cyan-800',
  };
  return (
    <div data-testid={testid}
         className={`px-2 py-1 rounded border v5-mono text-[10px] ${TONES[tone] || TONES.zinc}`}>
      <span className="opacity-60 mr-1">{label}</span>
      <span className="font-bold">{value}</span>
    </div>
  );
};

const ActionButton = ({ label, busy, onClick, testid, tone = 'cyan' }) => {
  const TONES = {
    cyan:    'bg-cyan-700/40 hover:bg-cyan-600/60 border-cyan-600 text-cyan-100',
    emerald: 'bg-emerald-700/40 hover:bg-emerald-600/60 border-emerald-600 text-emerald-100',
    amber:   'bg-amber-700/40 hover:bg-amber-600/60 border-amber-600 text-amber-100',
  };
  return (
    <button
      data-testid={testid}
      disabled={busy}
      onClick={onClick}
      className={`mt-2 px-3 py-1.5 rounded border v5-mono text-[11px] uppercase tracking-wide font-bold transition-colors ${TONES[tone] || TONES.cyan} disabled:opacity-40 disabled:cursor-not-allowed`}
    >
      {busy ? 'running…' : label}
    </button>
  );
};

const QueueDrawer = ({ check }) => {
  const pending  = check.pending  ?? '—';
  const claimed  = check.claimed  ?? '—';
  const completed = check.completed ?? '—';
  const failed   = check.failed   ?? '—';
  return (
    <div data-testid="readiness-drawer-queue_drained" className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <NumPill testid="queue-pending"  label="pending"  value={pending}
                 tone={pending > 0 ? 'rose' : 'emerald'} />
        <NumPill testid="queue-claimed"  label="claimed"  value={claimed}
                 tone={claimed > 0 ? 'amber' : 'emerald'} />
        <NumPill testid="queue-done"     label="completed" value={completed} tone="cyan" />
        <NumPill testid="queue-failed"   label="failed"   value={failed}
                 tone={failed > 0 ? 'amber' : 'emerald'} />
      </div>
      {(pending > 0 || claimed > 0) && (
        <div className="v5-mono text-[10px] text-zinc-400">
          Wait for the 4 turbo collectors to drain. The check polls every 30s; just
          leave it open. ETA ≈ {Math.ceil((pending + claimed) / 23)} min at the
          observed 232-req/10-min throughput.
        </div>
      )}
    </div>
  );
};

const CriticalSymbolsDrawer = ({ check, onAction, busy }) => {
  const stale = check.stale_symbols || [];
  if (!stale.length) {
    return (
      <div className="v5-mono text-[10px] text-emerald-300">
        All 10 critical symbols fresh on every required timeframe ✓
      </div>
    );
  }
  return (
    <div data-testid="readiness-drawer-critical_symbols_fresh" className="space-y-2">
      <div className="v5-mono text-[10px] text-rose-200">
        These critical symbols have at least one stale timeframe:
      </div>
      <div className="flex flex-wrap gap-1.5">
        {stale.map((s) => (
          <span key={s} data-testid={`stale-sym-${s}`}
                className="px-2 py-0.5 rounded border bg-rose-900/30 border-rose-800 text-rose-200 v5-mono text-[10px] font-bold">
            {s}
          </span>
        ))}
      </div>
      <ActionButton
        testid="action-fix-stale-critical"
        tone="amber"
        busy={busy}
        onClick={() => onAction('smart-backfill', { freshness_days: 1, tier_filter: 'intraday' })}
        label={`POST smart-backfill?freshness_days=1`}
      />
      <div className="v5-mono text-[9px] text-zinc-500">
        Smart-backfill now plans the union of (a) tier-required AND (b) bar_sizes
        the symbol already has data for — guaranteed to refresh these.
      </div>
    </div>
  );
};

const FreshnessDrawer = ({ check, onAction, busy }) => {
  const tfs = check.per_timeframe || [];
  return (
    <div data-testid="readiness-drawer-overall_freshness" className="space-y-2">
      {check.fresh_pct != null && (
        <div className="flex gap-1.5">
          <NumPill testid="freshness-pct" label="fresh_pct" value={`${check.fresh_pct}%`}
                   tone={check.fresh_pct >= 95 ? 'emerald'
                        : check.fresh_pct >= 70 ? 'amber' : 'rose'} />
          <NumPill testid="freshness-total" label="universe" value={check.total ?? '—'} />
        </div>
      )}
      {tfs.length > 0 && (
        <div className="space-y-1">
          <div className="v5-mono text-[9px] uppercase text-zinc-500 tracking-wide">
            By timeframe (worst-offender first)
          </div>
          {[...tfs].sort((a, b) => (a.fresh_pct ?? 0) - (b.fresh_pct ?? 0)).map((row) => {
            const pct = row.fresh_pct ?? 0;
            const tone = pct >= 95 ? 'emerald' : pct >= 70 ? 'amber' : 'rose';
            const TONES = {
              emerald: 'bg-emerald-500/60', amber: 'bg-amber-500/60', rose: 'bg-rose-500/60',
            };
            return (
              <div key={row.timeframe} data-testid={`tf-row-${row.timeframe}`}
                   className="flex items-center gap-2 v5-mono text-[10px]">
                <span className="w-14 shrink-0 opacity-70">{row.timeframe}</span>
                <span className="w-14 shrink-0 text-right tabular-nums">
                  {row.fresh}/{row.total}
                </span>
                <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div className={`h-full ${TONES[tone]}`} style={{ width: `${pct}%` }} />
                </div>
                <span className="w-12 shrink-0 text-right tabular-nums">
                  {pct.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      )}
      <ActionButton
        testid="action-refresh-stale-tfs"
        tone="cyan"
        busy={busy}
        onClick={() => onAction('smart-backfill', { freshness_days: 2, tier_filter: 'intraday' })}
        label="POST smart-backfill (refresh stale)"
      />
    </div>
  );
};

const NoDupesDrawer = ({ check }) => (
  <div data-testid="readiness-drawer-no_duplicates" className="v5-mono text-[10px] text-zinc-300">
    {check.detail}
    <div className="mt-1 text-[9px] text-zinc-500">
      O(1) check: the unique compound index on `(symbol, bar_size, date)` is
      asserted at write time, so duplicate bars are impossible by construction.
    </div>
  </div>
);

const DensityDrawer = ({ check }) => {
  const pct = check.dense_pct ?? null;
  const sample = check.low_density_sample || [];
  return (
    <div data-testid="readiness-drawer-density_adequate" className="space-y-2">
      {pct != null && (
        <NumPill label="dense_pct" testid="density-pct" value={`${pct}%`}
                 tone={pct >= 95 ? 'emerald' : pct >= 80 ? 'amber' : 'rose'} />
      )}
      {sample.length > 0 ? (
        <>
          <div className="v5-mono text-[9px] uppercase text-zinc-500 tracking-wide">
            Low-density sample (will be dropped from training)
          </div>
          <div className="flex flex-wrap gap-1">
            {sample.slice(0, 30).map((row, i) => (
              <span key={i}
                    className="px-1.5 py-0.5 rounded border bg-amber-900/20 border-amber-800/50 text-amber-200 v5-mono text-[9px]"
                    title={`${row.bars ?? '?'} bars`}>
                {row.symbol ?? row}{row.bars ? ` (${row.bars})` : ''}
              </span>
            ))}
            {sample.length > 30 && (
              <span className="v5-mono text-[9px] text-zinc-500">
                +{sample.length - 30} more
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="v5-mono text-[10px] text-zinc-300">
          No low-density symbols — every intraday symbol has ≥ 780 5-min bars.
        </div>
      )}
    </div>
  );
};

const DRAWER_BY_KEY = {
  queue_drained:          QueueDrawer,
  critical_symbols_fresh: CriticalSymbolsDrawer,
  overall_freshness:      FreshnessDrawer,
  no_duplicates:          NoDupesDrawer,
  density_adequate:       DensityDrawer,
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const BackfillReadinessCard = ({ refreshToken = 0 }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(null);   // which check key is open
  const [actionBusy, setActionBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(`${BACKEND_URL}/api/backfill/readiness`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshToken]);

  const runAction = useCallback(async (endpoint, params = {}) => {
    setActionBusy(true);
    setActionMsg(null);
    try {
      const qs = new URLSearchParams(params).toString();
      const url = `${BACKEND_URL}/api/ib-collector/${endpoint}${qs ? `?${qs}` : ''}`;
      const resp = await fetch(url, { method: 'POST' });
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(json.detail || `HTTP ${resp.status}`);
      const queued = json.queued ?? json.cancelled ?? 0;
      setActionMsg(
        json.success
          ? `Triggered ${endpoint} → ${queued} requests queued. Re-check in ~60s.`
          : `${endpoint} returned ${json.error || 'unknown error'}.`
      );
      // Re-poll readiness so the card reflects the new state.
      setTimeout(load, 2000);
    } catch (e) {
      setActionMsg(`Error: ${e.message || e}`);
    } finally {
      setActionBusy(false);
    }
  }, [load]);

  const verdict = data?.verdict || 'unknown';
  const style = VERDICT_STYLE[verdict] || VERDICT_STYLE.unknown;
  const checks = data?.checks || {};

  return (
    <section data-testid="backfill-readiness-card" data-help-id="backfill-readiness" className="space-y-2">
      <div className="v5-mono text-[10px] text-zinc-500 uppercase tracking-wide flex items-center gap-2">
        Backfill readiness · OK to train?
        {loading && (
          <span data-testid="readiness-loading" className="text-zinc-600">
            · loading…
          </span>
        )}
        <span className="ml-auto text-zinc-600 normal-case tracking-normal text-[9px]">
          tip: click a tile to drill in
        </span>
      </div>

      <div
        className={`flex items-start gap-3 p-3 rounded border ${style.pill}`}
        data-testid="readiness-verdict-pill"
        data-verdict={verdict}
      >
        <div className="flex items-center gap-2 shrink-0">
          <span className={`w-2.5 h-2.5 rounded-full ${style.dot}`} />
          <span className="v5-mono font-bold text-sm uppercase tracking-wider">
            {style.label}
          </span>
        </div>
        <div className="flex-1 min-w-0 v5-mono text-[11px] leading-tight pt-0.5">
          {error && !data && (
            <span className="text-rose-400" data-testid="readiness-error">
              /api/backfill/readiness unreachable — {error}
            </span>
          )}
          {data && <span className="opacity-90">{data.summary}</span>}
        </div>
      </div>

      {/* Inline action result (shown briefly after a tile button click) */}
      {actionMsg && (
        <div data-testid="readiness-action-msg"
             className="v5-mono text-[10px] px-2 py-1 rounded border bg-zinc-900/60 border-zinc-700 text-zinc-200">
          {actionMsg}
        </div>
      )}

      {data?.blockers?.length > 0 && (
        <div data-testid="readiness-blockers" className="v5-mono text-[10px] pl-3">
          <div className="text-rose-400 uppercase tracking-wide font-bold mb-0.5">Blockers</div>
          <ul className="list-disc pl-4 space-y-0.5 text-rose-200">
            {data.blockers.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      )}

      {data?.warnings?.length > 0 && (
        <div data-testid="readiness-warnings" className="v5-mono text-[10px] pl-3">
          <div className="text-amber-400 uppercase tracking-wide font-bold mb-0.5">Warnings</div>
          <ul className="list-disc pl-4 space-y-0.5 text-amber-200">
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Per-check matrix — clickable */}
      <div data-testid="readiness-checks-grid" className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1">
        {Object.entries(CHECK_LABELS).map(([key, label]) => {
          const c = checks[key];
          if (!c) return null;
          const cs = VERDICT_STYLE[c.status] || VERDICT_STYLE.unknown;
          const isOpen = expanded === key;
          const Drawer = DRAWER_BY_KEY[key];
          return (
            <div
              role="button"
              tabIndex={0}
              key={key}
              data-testid={`readiness-check-${key}`}
              data-expanded={isOpen}
              onClick={() => setExpanded(isOpen ? null : key)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setExpanded(isOpen ? null : key);
                }
              }}
              className={`cursor-pointer text-left px-2 py-1.5 rounded border ${cs.pill} hover:brightness-110 transition focus:outline-none focus:ring-1 focus:ring-cyan-500/40 ${isOpen ? 'sm:col-span-2 ring-1 ring-cyan-500/30' : ''}`}
            >
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full ${cs.dot}`} />
                <span className="v5-mono text-[10px] font-bold">{label}</span>
                <span className="v5-mono text-[9px] uppercase opacity-70 ml-auto">
                  {c.status}
                </span>
                <span className="v5-mono text-[10px] opacity-60 ml-1" aria-hidden>
                  {isOpen ? '▾' : '▸'}
                </span>
              </div>
              <div className="v5-mono text-[9px] opacity-75 mt-0.5">
                {c.detail}
              </div>
              {isOpen && Drawer && (
                <div
                  data-testid={`readiness-drawer-${key}`}
                  className="mt-2 pt-2 border-t border-current/20"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Drawer check={c} onAction={runAction} busy={actionBusy} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {data?.next_steps?.length > 0 && (
        <div data-testid="readiness-next-steps" className="v5-mono text-[10px] pl-3 pt-1">
          <div className="text-zinc-400 uppercase tracking-wide font-bold mb-0.5">Next steps</div>
          <ul className="list-disc pl-4 space-y-0.5 text-zinc-300">
            {data.next_steps.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};

export default BackfillReadinessCard;
