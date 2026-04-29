/**
 * FreshnessInspector — click the DataFreshnessBadge OR HealthChip to
 * open this modal. Shows:
 *   - /api/system/health subsystems (colored status grid)
 *   - /api/live/subscriptions (hot symbols + ref-counts)
 *   - /api/live/ttl-plan (cache TTLs per market state)
 *   - /api/live/pusher-rpc-health (RPC channel status)
 *
 * No mutation — pure observability surface. Auto-refresh every 15s while
 * open; stops polling on close.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, RefreshCw } from 'lucide-react';
import { BackfillReadinessCard } from './BackfillReadinessCard';
import { LastTrainingRunCard } from './LastTrainingRunCard';
import { LastTrophyRunCard } from './LastTrophyRunCard';
import { LastRunsTimeline } from './LastRunsTimeline';
import { CanonicalUniverseCard } from './CanonicalUniverseCard';
import { AutonomyReadinessCard } from './AutonomyReadinessCard';
import { MarketStateBanner } from './MarketStateBanner';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';
const POLL_MS = 15_000;

async function _get(path) {
  try {
    const resp = await fetch(`${BACKEND_URL}${path}`);
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

const STATUS_PILL = {
  green: 'bg-emerald-900/40 text-emerald-300 border-emerald-800/60',
  yellow: 'bg-amber-900/40 text-amber-300 border-amber-800/60',
  red: 'bg-rose-900/40 text-rose-300 border-rose-800/60',
};

export const FreshnessInspector = ({ isOpen, onClose, scrollToTestId = null }) => {
  const [health, setHealth] = useState(null);
  const [subs, setSubs] = useState(null);
  const [ttl, setTtl] = useState(null);
  const [rpc, setRpc] = useState(null);
  const [loading, setLoading] = useState(false);
  // Counter the BackfillReadinessCard watches — bumping it re-fetches
  // the readiness endpoint in sync with everything else in the modal.
  const [refreshCounter, setRefreshCounter] = useState(0);

  const reload = useCallback(async () => {
    if (!isOpen) return;
    setLoading(true);
    const [h, s, t, r] = await Promise.all([
      _get('/api/system/health'),
      _get('/api/live/subscriptions'),
      _get('/api/live/ttl-plan'),
      _get('/api/live/pusher-rpc-health'),
    ]);
    setHealth(h);
    setSubs(s);
    setTtl(t);
    setRpc(r);
    setLoading(false);
    setRefreshCounter((n) => n + 1);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;
    reload();
    const id = setInterval(reload, POLL_MS);
    return () => clearInterval(id);
  }, [isOpen, reload]);

  // Deep-link scroll: when the inspector is opened with a `scrollToTestId`,
  // scroll the matching element into view once the DOM has had a frame to
  // mount the cards. Used by the V5 header AutonomyVerdictChip to land
  // operators directly on the Autonomy card.
  useEffect(() => {
    if (!isOpen || !scrollToTestId) return undefined;
    const t = setTimeout(() => {
      const el = document.querySelector(`[data-testid="${scrollToTestId}"]`);
      if (el?.scrollIntoView) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 120);
    return () => clearTimeout(t);
  }, [isOpen, scrollToTestId]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 z-[60] flex items-start justify-center p-6 overflow-y-auto"
        data-testid="freshness-inspector"
        onClick={onClose}
      >
        <motion.div
          initial={{ y: -20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          className="bg-zinc-950 border border-zinc-800 rounded-lg w-full max-w-3xl shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
            <div className="flex items-center gap-2">
              <span className="v5-mono font-bold text-[13px] text-violet-400 uppercase">
                Freshness Inspector
              </span>
              {health && (
                <span className={`v5-mono text-[11px] px-1.5 py-0.5 rounded border uppercase ${STATUS_PILL[health.overall] || STATUS_PILL.yellow}`}>
                  {health.overall}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={reload}
                className="p-1.5 rounded hover:bg-zinc-800 transition-colors"
                data-testid="freshness-refresh"
                title="Refresh"
              >
                <RefreshCw className={`w-3.5 h-3.5 text-zinc-400 ${loading ? 'animate-spin' : ''}`} />
              </button>
              <button
                type="button"
                onClick={onClose}
                data-testid="freshness-close"
                className="p-1.5 rounded hover:bg-zinc-800 transition-colors"
              >
                <X className="w-3.5 h-3.5 text-zinc-400" />
              </button>
            </div>
          </div>

          <div className="p-4 space-y-4 max-h-[78vh] overflow-y-auto v5-scroll">
            {/* Weekend / Overnight banner — surfaces ONLY when buffers are
                active so operators don't mistake softer freshness warnings
                for a regression. Stays silent during RTH + extended hours.
                Drives off the same shared `useMarketState` hook as the
                V5 wordmark moon + DataFreshnessBadge chip. */}
            <MarketStateBanner />

            {/* Backfill readiness ("OK to train?") — surfaced first because
                it's the single most actionable signal right now while the
                historical backfill drains. */}
            <BackfillReadinessCard refreshToken={refreshCounter} />

            {/* Canonical universe — what training is about to do.
                Sourced from services/symbol_universe.py and shared with
                smart-backfill + readiness so all surfaces agree. */}
            <CanonicalUniverseCard refreshToken={refreshCounter} />

            {/* Last 5 runs sparkline — quick "did the latest run train fewer
                models than the previous one?" regression spotter. Reads
                from training_runs_archive (durable), no DB hunting. */}
            <LastRunsTimeline refreshToken={refreshCounter} limit={5} />

            {/* Last training run — sibling tile that closes the loop on
                "did the retrain actually produce models?" Highlights P5 +
                P8 specially since those have been the recurring failures
                across prior sessions. */}
            <LastTrainingRunCard refreshToken={refreshCounter} />

            {/* Last successful TROPHY run — permanent SLA badge that
                survives starting a new run. Reads from
                training_runs_archive (with a fallback synth from live
                status for the most recent run before archive existed). */}
            <LastTrophyRunCard refreshToken={refreshCounter} />

            {/* Autonomy readiness — single go/no-go gate before flipping
                auto-execute. Aggregates 7 sub-checks (account, pusher,
                live bars, trophy run, kill switch, EOD, risk consistency)
                + the auto-execute master-gate status. Drives off the
                shared AutonomyReadinessContext so the verdict stays in
                lock-step across the modal + future header chip / ⌘K. */}
            <AutonomyReadinessCard />

            {/* Subsystem grid */}
            <section data-testid="inspector-subsystems">
              <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide mb-1.5">
                Subsystems
              </div>
              {health?.subsystems ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                  {health.subsystems.map((s) => (
                    <div
                      key={s.name}
                      data-testid={`inspector-subsystem-${s.name}`}
                      className={`px-2.5 py-1.5 rounded border ${STATUS_PILL[s.status] || STATUS_PILL.yellow}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="v5-mono text-[12px] font-bold">{s.name}</span>
                        <span className="v5-mono text-[11px] uppercase opacity-70">{s.status}</span>
                      </div>
                      <div className="v5-mono text-[11px] opacity-75 mt-0.5 truncate" title={s.detail}>
                        {s.detail}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="v5-mono text-[12px] text-zinc-600">loading…</div>
              )}
            </section>

            {/* Live subscriptions */}
            <section data-testid="inspector-subs">
              <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide mb-1.5 flex items-center gap-2">
                Live subscriptions
                {subs && (
                  <span className="text-zinc-400">
                    {subs.active_count}/{subs.max_subscriptions}
                  </span>
                )}
              </div>
              {subs?.subscriptions?.length ? (
                <div className="space-y-0.5 v5-mono text-[12px]">
                  {subs.subscriptions.slice(0, 20).map((s) => (
                    <div
                      key={s.symbol}
                      data-testid={`inspector-sub-${s.symbol}`}
                      className="flex items-center gap-2 px-2 py-0.5 rounded hover:bg-zinc-900"
                    >
                      <span className="font-bold text-zinc-100 w-12">{s.symbol}</span>
                      <span className="text-zinc-500">ref×{s.ref_count}</span>
                      <span className="text-zinc-600">idle {Math.round(s.idle_seconds)}s</span>
                      <span className={`ml-auto text-[11px] ${s.pusher_ok ? 'text-emerald-500' : 'text-amber-500'}`}>
                        {s.pusher_ok ? 'pusher ok' : 'no pusher'}
                      </span>
                    </div>
                  ))}
                  {subs.subscriptions.length > 20 && (
                    <div
                      data-testid="inspector-subs-more"
                      className="px-2 py-1 text-[11px] text-zinc-600 uppercase tracking-wide"
                    >
                      +{subs.subscriptions.length - 20} more not shown
                    </div>
                  )}
                </div>
              ) : (
                <div className="v5-mono text-[12px] text-zinc-600">no active subscriptions</div>
              )}
            </section>

            {/* TTL plan + pusher RPC */}
            <section className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div data-testid="inspector-ttl">
                <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide mb-1.5">
                  Cache TTL plan
                </div>
                {ttl ? (
                  <div className="v5-mono text-[12px] space-y-0.5">
                    <div className="text-zinc-400">
                      current state: <span className="text-zinc-100 font-bold">{ttl.market_state}</span>
                    </div>
                    {Object.entries(ttl.ttl_by_state || {}).map(([k, v]) => (
                      <div key={k} className="flex gap-2 text-zinc-500">
                        <span className={`${k === ttl.market_state ? 'text-zinc-100 font-bold' : ''}`}>{k}</span>
                        <span className="ml-auto text-zinc-400">{v}s</span>
                      </div>
                    ))}
                    <div className="flex gap-2 text-zinc-500 pt-1 border-t border-zinc-900 mt-1">
                      <span>active view</span>
                      <span className="ml-auto text-zinc-400">{ttl.ttl_active_view}s</span>
                    </div>
                  </div>
                ) : (
                  <div className="v5-mono text-[12px] text-zinc-600">loading…</div>
                )}
              </div>
              <div data-testid="inspector-rpc">
                <div className="v5-mono text-[12px] text-zinc-500 uppercase tracking-wide mb-1.5">
                  Pusher RPC
                </div>
                {rpc ? (
                  <div className="v5-mono text-[12px] space-y-0.5 text-zinc-400">
                    <div>
                      reachable: <span className={rpc.reachable ? 'text-emerald-400' : 'text-amber-400'}>
                        {String(rpc.reachable)}
                      </span>
                    </div>
                    <div className="truncate">url: <span className="text-zinc-100">{rpc.client?.url || 'n/a'}</span></div>
                    <div>enabled: <span className="text-zinc-100">{String(rpc.client?.enabled)}</span></div>
                    <div>failures: <span className="text-zinc-100">{rpc.client?.consecutive_failures ?? 0}</span></div>
                  </div>
                ) : (
                  <div className="v5-mono text-[12px] text-zinc-600">loading…</div>
                )}
              </div>
            </section>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export default FreshnessInspector;
